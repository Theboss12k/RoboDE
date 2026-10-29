import asyncio
import json
import time
import httpx
import pytest
from integrations.gcp.idle_guard import should_stop
from integrations.gcp.lifecycle import GpuLifecycle
from services.api.storage import atomic_json


def test_guest_guard_ignores_observation_files_and_rejects_future_stamps(tmp_path):
    atomic_json(tmp_path/'guard.json',{'last_work':1000})
    assert should_stop(tmp_path,100,701,600)
    atomic_json(tmp_path/'nurec.json',{'last_work':695})
    assert not should_stop(tmp_path,100,701,600)
    atomic_json(tmp_path/'nurec.json',{'last_work':999999})
    assert should_stop(tmp_path,100,701,600)


def configure(store):
    atomic_json(store.runtime/'connections/isaac.json',dict(on_demand=True,gcp_project='test-project',gcp_zone='zone-a',gcp_instance='robot-vm',url='http://127.0.0.1:9100',token='a'*24))


def test_on_demand_start_sets_and_verifies_cloud_limit_before_boot(store,monkeypatch):
    configure(store);calls=[];vm={'status':'TERMINATED','scheduling':{}}
    async def runner(args):
        calls.append(args)
        if args[2]=='set-scheduling':vm['scheduling']={'instanceTerminationAction':'STOP','maxRunDuration':{'seconds':'7200'},'automaticRestart':False}
        if args[2]=='start':vm['status']='RUNNING'
        return vm
    original=httpx.AsyncClient
    def response(req):return httpx.Response(200,json={'protocol':'robot-ide.isaac.v1','idle_guard_active':True,'idle_timeout_seconds':600})
    monkeypatch.setattr('integrations.gcp.lifecycle.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(response),**kw))
    async def run():
        lifecycle=GpuLifecycle(store,runner)
        # Read-only status does not execute cloud commands.
        assert (await lifecycle.snapshot())['status']=='unknown'
        assert not calls
        lifecycle.request_start();await lifecycle.task
        assert lifecycle.state['status']=='ready',lifecycle.state
        assert [c[2] for c in calls]==['describe','set-scheduling','describe','start']
        assert '--instance-termination-action=STOP' in calls[1]
        await lifecycle.close()
    asyncio.run(run())


def test_refuses_to_adopt_unprotected_running_vm(store):
    configure(store);calls=[]
    async def runner(args):calls.append(args);return {'status':'RUNNING','scheduling':{}}
    async def run():
        lifecycle=GpuLifecycle(store,runner);lifecycle.request_start();await lifecycle.task
        assert lifecycle.state['status']=='error'
        assert 'runtime limit' in lifecycle.state['message']
        assert len(calls)==1
    asyncio.run(run())


def test_failed_worker_start_automatically_stops_newly_booted_vm(store,monkeypatch):
    configure(store);calls=[]
    vm={'status':'TERMINATED','scheduling':{'instanceTerminationAction':'STOP','maxRunDuration':{'seconds':'7200'},'automaticRestart':False}}
    async def runner(args):calls.append(args);return vm
    original=httpx.AsyncClient
    monkeypatch.setattr('integrations.gcp.lifecycle.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda req:httpx.Response(503)),**kw))
    async def run():
        lifecycle=GpuLifecycle(store,runner);lifecycle.ready_timeout=.01;lifecycle.poll_interval=.01
        lifecycle.request_start();await lifecycle.task
        assert lifecycle.state['status']=='error'
        assert calls[-1][2]=='stop'
    asyncio.run(run())


def test_tunnel_uses_expiring_dedicated_key_without_exposing_worker_token(store,tmp_path,monkeypatch):
    key=tmp_path/'SSH key';key.write_text('test-only key')
    calls=[]
    async def spawn(*args,**kwargs):
        calls.append(args)
        return type('Process',(),{'returncode':None})()
    monkeypatch.setattr('integrations.gcp.lifecycle.asyncio.create_subprocess_exec',spawn)
    config=dict(url='http://127.0.0.1:9100',gcp_instance='vm',gcp_project='project',gcp_zone='zone',
                ssh_key_file=str(key),use_iap=False,token='private-worker-token')
    lifecycle=GpuLifecycle(store)
    asyncio.run(lifecycle._open_tunnel(config))
    assert '--ssh-key-file='+str(key) in calls[0]
    assert '--ssh-key-expire-after=2h' in calls[0]
    assert 'BatchMode=yes' in calls[0]
    assert '--tunnel-through-iap' not in calls[0]
    assert all(config['token'] not in arg for arg in calls[0])
    config['ssh_key_file']=str(tmp_path/'missing-key')
    lifecycle.tunnel=None
    with pytest.raises(ValueError,match='SSH key is missing'):
        asyncio.run(lifecycle._open_tunnel(config))
    assert len(calls)==1


async def test_start_retries_a_tunnel_that_exits_during_vm_boot(store,monkeypatch):
    configure(store)
    lifecycle=GpuLifecycle(store)
    async def runner(args):
        return {'status':'RUNNING','scheduling':{'instanceTerminationAction':'STOP','maxRunDuration':{'seconds':'7200'},'automaticRestart':False}}
    # Exercise the real-runner branch without executing any cloud command.
    lifecycle._run=runner;lifecycle.runner=runner;lifecycle.poll_interval=.001
    opens=[]
    async def open_tunnel(config):
        opens.append(True)
        lifecycle.tunnel=type('Process',(),{'returncode':255 if len(opens)==1 else None})()
    monkeypatch.setattr(lifecycle,'_open_tunnel',open_tunnel)
    original=httpx.AsyncClient
    def response(request):
        assert len(opens)==2
        return httpx.Response(200,json={'protocol':'robot-ide.isaac.v1','idle_guard_active':True,'idle_timeout_seconds':600})
    monkeypatch.setattr('integrations.gcp.lifecycle.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(response),**kw))
    lifecycle.request_start();await lifecycle.task
    assert lifecycle.state['status']=='ready'
    assert len(opens)==2
