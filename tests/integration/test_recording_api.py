import asyncio
import json
from types import SimpleNamespace
import httpx
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.execution.recordings import Recordings
from services.execution.controller import SimulationController
from tests.adapter_contracts.test_scene_video_worker import connected_recording


def test_recording_requires_connection_without_starting_gpu_and_validates_input(store,monkeypatch):
    app=create_app(store)
    def forbidden():raise AssertionError('Recording panel must not boot a GPU')
    monkeypatch.setattr(app.state.controller.gpu,'request_start',forbidden)
    with TestClient(app) as client:
        base='/api/projects/apple_transfer/recordings'
        assert client.get(base).json()==[]
        assert client.get(base+'/capabilities').json()['available'] is False
        assert client.post(base,json={}).status_code==422
        assert client.post(base,json={'duration_seconds':301}).status_code==422
        assert client.get('/api/projects/missing/recordings').status_code==422


async def test_recording_export_survives_worker_disconnect_and_blocks_only_scene_changes(store,model,instance,tmp_path):
    remote,backend,_=await connected_recording(store,model,instance,tmp_path)
    controller=SimulationController(store)
    controller.sessions['apple_transfer']=SimpleNamespace(remote=remote,backend='isaac_sim')
    service=controller.recordings
    record=await service.start('apple_transfer',{'resolution':'640x360','duration_seconds':3})
    # Recording owns no motion resources and does not prevent planning/execution.
    controller.ensure_idle('apple_transfer')
    assert not controller.resources.owners and not controller.leases
    for operation in (controller.reset,controller.disconnect):
        try:
            await operation('apple_transfer')
        except ValueError as error:
            assert 'recording' in str(error)
        else:raise AssertionError('Scene mutation was allowed while recording')
    try:
        await controller.switch_backend('apple_transfer','mock')
    except ValueError as error:assert 'recording' in str(error)
    else:raise AssertionError('Simulator switch was allowed while recording')
    await remote.advance({'arm_01':remote.latest.states['arm_01'].positions},1/30)
    assert backend.backend.tick_count==1
    await service.stop('apple_transfer',record['id'])
    await asyncio.wait_for(service.jobs[record['id']],10)
    finished=service.get('apple_transfer',record['id'])
    assert finished['status']=='ready' and finished['cached']
    assert len(finished['sha256'])==64
    controller.recordings.guard('apple_transfer')
    await remote.disconnect()
    controller.sessions.clear()
    reopened=Recordings(controller)
    assert reopened.listing('apple_transfer')[0]['cached']
    app=create_app(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
        response=await client.get(f"/api/projects/apple_transfer/recordings/{record['id']}/file")
        assert response.status_code==200 and response.headers['content-type']=='video/mp4'
        assert response.headers['x-content-sha256']==finished['sha256']
        assert len(response.content)==finished['byte_length']
    await controller.close()


async def test_runtime_restart_recovers_history_without_permanent_guard(store,model,instance,tmp_path):
    remote,backend,_=await connected_recording(store,model,instance,tmp_path)
    controller=SimulationController(store)
    controller.sessions['apple_transfer']=SimpleNamespace(remote=remote,backend='isaac_sim')
    record=await controller.recordings.start('apple_transfer',{'resolution':'640x360'})
    controller.recordings.jobs[record['id']].cancel()
    await asyncio.gather(*controller.recordings.jobs.values(),return_exceptions=True)
    reopened=Recordings(controller)
    assert reopened.get('apple_transfer',record['id'])['status']=='interrupted'
    reopened.guard('apple_transfer')
    # Worker capture can be rediscovered without changing or resetting its scene.
    recovered=await reopened.recover('apple_transfer')
    assert recovered[0]['status']=='recording'
    await reopened.stop('apple_transfer',record['id'])
    await asyncio.wait_for(reopened.jobs[record['id']],10)
    assert reopened.get('apple_transfer',record['id'])['cached']
    await remote.disconnect()
    controller.sessions.clear()
    await controller.close()


def test_legacy_workers_have_clear_capability_message(store):
    controller=SimulationController(store)
    controller.sessions['apple_transfer']=SimpleNamespace(remote=SimpleNamespace(metadata={}))
    capability=controller.recordings.capability('apple_transfer')
    assert not capability['available'] and 'Update' in capability['reason']


async def test_video_download_gateway_auth_filename_and_business_boundary(store,tmp_path):
    from services.api.storage import atomic_json
    from web.gateway import create_gateway
    import hashlib
    rid='b'*32
    video=b'\x00\x00\x00\x20ftypisom'+b'fixture-video'*10
    digest=hashlib.sha256(video).hexdigest()
    runtime=create_app(store)
    folder=runtime.state.controller.recordings.folder('apple_transfer')
    (folder/(rid+'.mp4')).write_bytes(video)
    atomic_json(folder/(rid+'.json'),{'id':rid,'project_id':'apple_transfer','cached':True,'status':'ready','sha256':digest,'created_at':'2026-10-29'})
    dist=tmp_path/'dist';dist.mkdir();(dist/'index.html').write_text('IDE')
    for scope in ('ide','business'):
        gateway=create_gateway(dist=dist,code='scene-recording-test-code',scope=scope,transport=httpx.ASGITransport(app=runtime))
        async with gateway.router.lifespan_context(gateway):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway),base_url='https://workspace.example') as client:
                url=f'/api/projects/apple_transfer/recordings/{rid}/file'
                assert (await client.get(url)).status_code==401
                await client.post('/login',content='code=scene-recording-test-code')
                response=await client.get(url)
                if scope=='business':
                    assert response.status_code==404
                else:
                    assert response.status_code==200 and response.content==video
                    assert response.headers['x-content-sha256']==digest
                    assert response.headers['cache-control']=='no-store'
                    assert '.mp4' in response.headers['content-disposition']
