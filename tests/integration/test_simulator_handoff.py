"""Scene hand-off contracts; no native GPU or cloud resources are used."""
import copy
import httpx
import pytest
from services.api.main import create_app
from services.api.storage import atomic_json
from scripts.contract_scene import ContractScene,connect_factory


async def test_round_trip_preserves_multi_robot_current_scene_and_saved_starts(store):
    app=create_app(store);controller=app.state.controller;backend=ContractScene()
    controller.remote_factory=connect_factory(backend)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
        result=await client.post('/api/projects/apple_transfer/robots',json={'id':'arm_02','name':'Second arm','base_pose':{'x':1.1,'y':.2,'z':0.,'yaw':.6}})
        assert result.status_code==201,result.text
        saved={p:p.read_bytes() for p in (store.project_folder('apple_transfer')/'robots').rglob('*.yaml')}
        history=store.project_folder('apple_transfer')/'runs/unchanged.json';atomic_json(history,{'revision':'original','positions':{'arm_01':1}})
        saved[history]=history.read_bytes()
        *_,session,_=await controller.context('apple_transfer')
        positions={}
        for index,(rid,adapter) in enumerate(session.adapters.items()):
            q={**(await adapter.get_state()).positions,'base_yaw':.3+index*.2}
            await adapter.command(q);await adapter.request_stop();positions[rid]=q
        session.objects[0].position.x+=.13
        objects=copy.deepcopy(session.objects)
        result=await client.put('/api/projects/apple_transfer/simulation',json={'adapter':'isaac_sim'})
        assert result.status_code==200,result.text
        assert result.json()['scene_transferred'] and result.json()['robots']==2
        assert len(backend.loads)==1 and backend.resets==1
        transferred=backend.loads[0]
        assert transferred.transfer_positions==positions and transferred.objects==objects
        assert transferred.robots[1]['instance']['base_pose']=={'x':1.1,'y':.2,'z':0.,'yaw':.6}
        assert {r:s.positions for r,s in backend.states.items()}==positions
        # A repeated Connect reads the native scene without resetting it.
        await client.put('/api/projects/apple_transfer/simulation',json={'adapter':'isaac_sim'})
        assert len(backend.loads)==1 and backend.resets==1
        positions['arm_02']['elbow']+=.1;objects[0].position.y+=.09
        backend.reset(positions,objects)
        result=await client.put('/api/projects/apple_transfer/simulation',json={'adapter':'mock'})
        assert result.status_code==200,result.text
        *_,session,_=await controller.context('apple_transfer')
        assert {rid:s.positions for rid,s in (await controller.states(session)).items()}==positions
        assert session.objects==objects
        await controller.disconnect('apple_transfer')
        *_,session,_=await controller.context('apple_transfer')
        assert session.objects==objects and (await controller.states(session))['arm_02'].positions==positions['arm_02']
        assert all(p.read_bytes()==value for p,value in saved.items())
    await controller.close()


async def test_failed_transfer_restores_previous_choice_and_current_scene(store):
    backend=ContractScene();backend.metadata={**backend.metadata,'scene_loading':False}
    app=create_app(store);controller=app.state.controller;controller.remote_factory=connect_factory(backend)
    path=store.project_folder('apple_transfer')/'project.yaml';original=path.read_bytes()
    *_,session,_=await controller.context('apple_transfer')
    q={**(await session.adapter.get_state()).positions,'base_yaw':.65}
    await session.adapter.command(q);await session.adapter.request_stop();session.objects[0].position.z+=.1
    original_objects=copy.deepcopy(session.objects)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
        response=await client.put('/api/projects/apple_transfer/simulation',json={'adapter':'isaac_sim'})
        assert response.status_code==502 and 'managed Isaac worker' in response.text
        assert path.read_bytes()==original and not controller.resources.owners
        *_,restored,state=await controller.context('apple_transfer')
        assert state.positions==q and restored.objects==original_objects and state.connected
        assert not backend.loads
    await controller.close()


async def test_manual_ownership_and_grasps_block_scene_switch(store):
    controller=create_app(store).state.controller
    *_,session,_=await controller.context('apple_transfer')
    controller.resources.acquire(['environment:apple_transfer'],'controls')
    with pytest.raises(ValueError,match='manual control'):await controller.switch_backend('apple_transfer','isaac_sim')
    controller.resources.release('controls')
    session.held_object='apple'
    with pytest.raises(ValueError,match='Release held objects'):await controller.switch_backend('apple_transfer','isaac_sim')
    session.held_object=None
    await controller.close()


async def test_destination_claimed_during_observation_keeps_source_connected(store):
    from services.execution.resources import environment_resource
    controller=create_app(store).state.controller
    *_,session,_=await controller.context('apple_transfer')
    original_states=controller.states
    async def raced_states(cell):
        states=await original_states(cell)
        controller.resources.acquire([environment_resource('another_project','isaac_sim')],'other-controls')
        return states
    controller.states=raced_states
    with pytest.raises(ValueError,match='already controlled'):await controller.switch_backend('apple_transfer','isaac_sim')
    assert controller.sessions['apple_transfer'] is session
    assert (await session.adapter.get_state()).connected
    assert controller.storage.load_project('apple_transfer')[0]['simulation']['adapter']=='mock'
    controller.resources.release('other-controls')
    await controller.close()
