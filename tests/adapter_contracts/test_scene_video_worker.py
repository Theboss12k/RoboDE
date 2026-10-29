import asyncio
import httpx
import pytest
from tests.adapter_contracts.test_isaac_worker import ContractCell, TOKEN
from simulation.isaac_sim.worker import create_worker
from simulation.isaac_sim.recording import RecordingBackend
from robot_system.registry.models.demo_arm.adapters.isaac_sim.adapter import IsaacCell
from tests.unit.test_scene_recording import Pixels


async def connected_recording(store, model, instance, tmp_path, lease_seconds=20):
    objects=store.load_project('apple_transfer')[-1]
    native=ContractCell(model,instance,objects)
    backend=RecordingBackend(native,root=tmp_path/'worker-videos',camera_factory=Pixels)
    app=create_worker(backend,TOKEN,lease_seconds=lease_seconds)
    client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://worker',headers={'Authorization':f'Bearer {TOKEN}'})
    cell=IsaacCell('apple_transfer',[instance],backend.models,objects,client=client,require_native=False)
    await cell.connect()
    return cell,backend,app


async def test_worker_recording_auth_ownership_motion_and_reset_guards(store,model,instance,tmp_path):
    cell,backend,app=await connected_recording(store,model,instance,tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://worker') as anonymous:
        assert (await anonymous.get('/v1/recordings/'+'a'*32,params={'project_id':'apple_transfer'})).status_code==401
    prefix=f'/v1/sessions/{cell.session_id}'
    record=await cell.request('POST',prefix+'/recordings',{'resolution':'640x360'})
    assert backend.backend.tick_count==0
    assert (await cell.client.post(prefix+'/recordings',json={})).status_code==422
    q=cell.latest.states['arm_01'].positions
    await cell.advance({'arm_01':q},1/30)
    assert backend.backend.tick_count==1  # Only the explicit motion advances physics.
    response=await cell.client.post(prefix+'/reset',json={'positions':{'arm_01':q},'objects':[o.model_dump() for o in cell.objects]})
    assert response.status_code==422 and 'recording' in response.text
    assert backend.backend.tick_count==1
    rid=record['id']
    assert (await cell.client.get('/v1/recordings/'+rid,params={'project_id':'other'})).status_code==422
    await cell.stop()  # Robot Stop does not terminate a video.
    assert backend.recorder.current['status']=='recording'
    await cell.request('POST',prefix+f'/recordings/{rid}/stop')
    await asyncio.to_thread(backend.recorder.close)
    video=await cell.client.get('/v1/recordings/'+rid+'/file',params={'project_id':'apple_transfer'})
    assert video.status_code==200 and video.headers['content-type']=='video/mp4'
    assert len(video.content)>32
    assert (await cell.request('GET',prefix+'/recordings'))[0]['id']==rid
    await cell.disconnect()


async def test_session_expiry_finalizes_recording_and_keeps_history(store,model,instance,tmp_path):
    cell,backend,_=await connected_recording(store,model,instance,tmp_path,lease_seconds=.01)
    # Start must fit inside the short lease; expiry applies to the next request.
    record=await cell.request('POST',f'/v1/sessions/{cell.session_id}/recordings',{'resolution':'640x360'})
    await asyncio.sleep(.025)
    response=await cell.client.get('/v1/recordings/'+record['id'],params={'project_id':'apple_transfer'})
    assert response.status_code==409
    await asyncio.to_thread(backend.recorder.close)
    result=await cell.request('GET','/v1/recordings/'+record['id']+'?project_id=apple_transfer')
    assert result['status']=='ready'
    assert result['stop_reason']=='Worker session ended or expired'
    await cell.client.aclose()
