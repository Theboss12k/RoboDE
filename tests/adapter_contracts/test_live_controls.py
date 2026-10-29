import asyncio
import time
import pytest
from shared.models.domain import now
from services.adapters import controls as controls_module
from services.adapters.controls import ManualControls
from services.adapters.generation import AdapterRegistry,GenerateAdapter
from services.execution.controller import SimulationController
from integrations.ros2.bridge import create_bridge
from fastapi.testclient import TestClient


class FakeController:
    def __init__(self):
        self.positions={'j1':0.}
        self.stop_calls=0
        self.command_calls=0
    def state(self):
        return {'positions':self.positions,'stopped':True,'measured_at':now(),'device_id':'controller-serial-123','ready':True,'stop_supported':True}
    async def stop(self):
        self.stop_calls+=1
        return self.state()
    async def command(self,positions,duration):
        self.command_calls+=1
        self.positions=positions
        return self.state()
    def close(self):pass


def test_ros_bridge_auth_ownership_and_expiry():
    controller=FakeController()
    token='test-bridge-token-123456'
    with TestClient(create_bridge(controller,token,lease_timeout=.1)) as client:
        assert client.post('/v1/state').status_code==401
        first={'Authorization':'Bearer '+token,'X-Control-Session':'first'}
        second={**first,'X-Control-Session':'second'}
        assert client.post('/v1/state',headers=first).status_code==200
        assert client.post('/v1/command',headers=first,json={'positions':{'j1':.01},'duration':1}).status_code==409
        assert client.post('/v1/stop',headers=first).json()['stopped']
        assert client.post('/v1/stop',headers=second).status_code==409
        assert client.post('/v1/state',headers=second).json()['ready'] is False
        assert client.post('/v1/command',headers=first,json={'positions':{'j1':.01},'duration':1}).status_code==200
        assert controller.command_calls==1
        time.sleep(.4)
        assert controller.stop_calls>=2
        assert client.post('/v1/stop',headers=second).status_code==200
        assert client.post('/v1/disconnect',headers=second).json()['stopped']


async def test_live_controls_require_review_validation_arm_and_share_device_lease(store,instance,monkeypatch):
    registry=AdapterRegistry(store)
    bundle=await registry.generate(GenerateAdapter(model_id='demo_arm',name='ROS physical',kind='ros2',connection={'bridge_url':'http://bridge-one:8767'}),instance['initial_configuration']['actuator_positions'])
    registry.review(bundle['id'],bundle['hash'])
    await registry.test(bundle['id'])
    class FakeLiveProcess:
        def __init__(self):
            self.positions=dict(instance['initial_configuration']['actuator_positions'])
        async def start(self,*args):return self.state()
        def state(self):
            return {'positions':self.positions,'stopped':True,'connected':True,'measured_at':now(),'source':'hardware','device_id':'same-physical-controller','ready':True,'stop_supported':True}
        async def request(self,data):
            if data['operation']=='command':self.positions=data['positions']
            return self.state()
        async def close(self):pass
    monkeypatch.setattr(controls_module,'AdapterProcess',FakeLiveProcess)
    monkeypatch.setenv('ROS_BRIDGE_TOKEN','test-auth-token-at-least-16')
    runtime=SimulationController(store)
    controls=ManualControls(registry,runtime)
    first=await controls.open('apple_transfer','arm_01',bundle['id'],'live')
    sid=first['id']
    assert not first['armed'] and not first['connection_validated']
    with pytest.raises(ValueError,match='Arm'):
        await controls.command(sid,{**first['feedback']['positions'],'base_yaw':.05})
    await controls.validate(sid)
    assert (await controls.arm(sid))['armed']
    moved=await controls.command(sid,{**first['feedback']['positions'],'base_yaw':.05})
    assert moved['feedback']['positions']['base_yaw']==.05
    other=store.create_project('Other project')
    with pytest.raises(ValueError,match='already controlled'):
        await controls.open(other['id'],'arm_01',bundle['id'],'live')
    with pytest.raises(ValueError,match='limited'):
        await controls.command(sid,{**moved['feedback']['positions'],'base_yaw':1.})
    assert not controls.public(controls.sessions[sid])['armed']
    await controls.validate(sid)
    await controls.arm(sid)
    controls.sessions[sid]['armed_until']=time.monotonic()-1
    assert not (await controls.read(sid))['armed']
    assert (await controls.read(sid))['stop_requested']
    await controls.close_session(sid)
    next_session=await controls.open(other['id'],'arm_01',bundle['id'],'live')
    assert not next_session['armed']
    await controls.close()
    await runtime.close()
