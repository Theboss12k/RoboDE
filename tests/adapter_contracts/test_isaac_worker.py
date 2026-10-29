import copy
import httpx
import pytest
from fastapi.testclient import TestClient
from shared.models.domain import RobotState,now
from simulation.isaac_sim.worker import create_worker
from robot_system.registry.models.demo_arm.adapters.isaac_sim.adapter import IsaacCell,WorkerUnavailable
from services.planning.kinematics import with_base

TOKEN='test-worker-token-123456'


class ContractCell:
    metadata={'engine':'contract_test','physics_available':False,'simulator_version':'test','asset_sha256':'test-only'}
    def __init__(self,model,instance,objects):
        rid=instance['instance']['id']
        self.models={rid:with_base(model,instance)}
        self.states={rid:RobotState(instance_id=rid,positions=dict(instance['initial_configuration']['actuator_positions']),source='simulation')}
        self.objects=objects
        self.tick_count=0
        self.simulation_time=0.
    def validate_scene(self,request):
        if {r['instance']['instance']['id'] for r in request.robots} != set(self.models):
            raise ValueError('Robot mapping mismatch')
    def observe(self):
        stamp=now()
        for state in self.states.values():
            state.measured_at=stamp
        return {'states':{r:s.model_dump() for r,s in self.states.items()},'objects':[o.model_dump() for o in self.objects],
                'measured_at':stamp,'simulation_time':self.simulation_time,'faults':[]}
    def advance(self,positions,dt):
        self.tick_count+=1
        self.simulation_time+=dt
        for rid,q in positions.items():
            self.states[rid].positions=dict(q)
            self.states[rid].stopped=False
    def stop(self):
        for state in self.states.values():state.stopped=True
    def reset(self,positions,objects):
        self.advance(positions,1/30)
        self.objects=objects
        self.stop()


async def connected(store,model,instance):
    objects=store.load_project('apple_transfer')[-1]
    backend=ContractCell(model,instance,objects)
    app=create_worker(backend,TOKEN)
    client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://worker',headers={'Authorization':f'Bearer {TOKEN}'})
    cell=IsaacCell('apple_transfer',[instance],backend.models,objects,client=client,require_native=False)
    await cell.connect()
    return cell,backend,app


async def test_adapter_contract_connection_does_not_initialize_or_move(store,model,instance):
    cell,backend,_=await connected(store,model,instance)
    assert backend.tick_count==0
    before=copy.deepcopy(cell.latest.states['arm_01'].positions)
    await cell.advance({'arm_01':{**before,'base_yaw':.1}},1/30)
    assert backend.tick_count==1
    assert cell.latest.states['arm_01'].positions['base_yaw']==.1
    assert cell.latest.states['arm_01'].stopped is False
    assert (await cell.stop()).states['arm_01'].stopped
    assert instance['initial_configuration']['actuator_positions']==before
    await cell.disconnect()


async def test_native_adapter_rejects_contract_test_backend(store,model,instance):
    cell,backend,app=await connected(store,model,instance)
    native=IsaacCell('apple_transfer',[instance],backend.models,backend.objects,client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://worker',headers={'Authorization':f'Bearer {TOKEN}'}))
    with pytest.raises(WorkerUnavailable,match='contract-test'):
        await native.connect()
    await native.client.aclose()
    await cell.disconnect()


async def test_out_of_order_ticks_and_exclusive_worker_lease(store,model,instance):
    cell,backend,app=await connected(store,model,instance)
    body={'sequence':2,'dt':1/30,'positions':{'arm_01':cell.latest.states['arm_01'].positions}}
    result=await cell.client.post(f'/v1/sessions/{cell.session_id}/step',json=body)
    assert result.status_code==409
    assert backend.tick_count==0
    other=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://worker',headers={'Authorization':f'Bearer {TOKEN}'})
    result=await other.post('/v1/sessions',json={'project_id':'other','robots':[],'objects':[]})
    assert result.status_code==409
    await other.aclose()
    await cell.disconnect()


async def test_invalid_commands_do_not_partially_advance(store,model,instance):
    cell,backend,_=await connected(store,model,instance)
    positions=dict(cell.latest.states['arm_01'].positions)
    with pytest.raises(ValueError):
        await cell.advance({'arm_01':{**positions,'elbow':999}},1/30)
    assert backend.tick_count==0
    await cell.disconnect()


async def test_stale_feedback_rejected(store,model,instance):
    cell,_,_=await connected(store,model,instance)
    data=cell.latest.model_dump()
    data['measured_at']='2000-01-01T00:00:00+00:00'
    with pytest.raises(WorkerUnavailable,match='stale'):
        cell.accept(data)
    await cell.disconnect()


def test_worker_requires_authentication_and_strong_token(store,model,instance):
    backend=ContractCell(model,instance,store.load_project('apple_transfer')[-1])
    with pytest.raises(ValueError):create_worker(backend,'short')
    with TestClient(create_worker(backend,TOKEN)) as client:
        assert client.get('/v1/health').status_code==401
        assert client.get('/v1/health',headers={'Authorization':f'Bearer {TOKEN}'}).json()['engine']=='contract_test'


async def test_remote_runtime_never_synthesizes_object_success(store,model,instance):
    import yaml
    from services.execution.controller import SimulationController
    from services.ai_orchestrator.providers import TemplateProvider
    from services.planning.planner import build_plan
    from services.api.storage import fingerprint
    from shared.models.domain import Lifecycle
    objects=store.load_project('apple_transfer')[-1]
    backend=ContractCell(model,instance,objects)
    app=create_worker(backend,TOKEN)
    def factory(pid,instances,models,objects):
        return IsaacCell(pid,instances,models,objects,client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://worker',headers={'Authorization':f'Bearer {TOKEN}'}),require_native=False)
    path=store.project_folder('apple_transfer')/'project.yaml'
    project=yaml.safe_load(path.read_text());project['simulation']={'adapter':'isaac_sim'};path.write_text(yaml.safe_dump(project))
    runtime=SimulationController(store,speed=500,remote_factory=factory)
    _,instance,placed_model,session,state=await runtime.context('apple_transfer')
    provider=TemplateProvider()
    intent=await provider.interpret(project['default_prompt'],session.objects)
    snapshot=await runtime.snapshot(project['id'])
    plan=build_plan(project['id'],project['default_prompt'],intent,provider.name,placed_model,instance,session.objects,state.positions,fingerprint(snapshot))
    plan.adapter='isaac_sim'
    store.save_plan(plan,snapshot)
    # Execute over the remote transport at normal timing; a fixed scene must fail outcome verification.
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,project['id'])
    await runtime.jobs[run.id]
    assert run.status==Lifecycle.FAILED
    assert run.evidence['object_inside_target'] is False
    assert run.evidence['physics_simulated'] is False
    assert backend.tick_count==len(plan.frames)-1
    await runtime.close()


def test_main_thread_bridge_never_calls_physics_on_http_thread():
    import threading
    import time
    from simulation.isaac_sim.bridge import MainThreadBridge
    class Backend:
        models={}
        metadata={}
        def observe(self):return threading.get_ident()
    bridge=MainThreadBridge(Backend())
    results=[]
    http=threading.Thread(target=lambda:results.append(bridge.observe()))
    http.start()
    bridge.pump(timeout=1)
    http.join(timeout=2)
    assert results==[threading.get_ident()]


async def test_reconnect_resets_tick_sequence_without_initializing_scene(store,model,instance):
    cell,backend,_=await connected(store,model,instance)
    await cell.advance({'arm_01':cell.latest.states['arm_01'].positions},1/30)
    await cell.client.delete(f'/v1/sessions/{cell.session_id}')
    await cell.connect()
    assert cell.sequence==0
    assert backend.tick_count==1
    await cell.disconnect()


def test_lost_worker_can_be_replaced_with_local_preview_without_feedback_replay(store,model,instance):
    import yaml
    from services.api.main import create_app
    backend=ContractCell(model,instance,store.load_project('apple_transfer')[-1])
    worker=create_worker(backend,TOKEN)
    path=store.project_folder('apple_transfer')/'project.yaml'
    project=yaml.safe_load(path.read_text());project['simulation']={'adapter':'isaac_sim'};path.write_text(yaml.safe_dump(project))
    app=create_app(store)
    cells=[]
    def factory(pid,instances,models,objects):
        cell=IsaacCell(pid,instances,models,objects,client=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker),base_url='http://worker',headers={'Authorization':f'Bearer {TOKEN}'}),require_native=False)
        cells.append(cell)
        return cell
    app.state.controller.remote_factory=factory
    with TestClient(app) as client:
        assert client.get('/api/projects/apple_transfer').status_code==200
        cells[0].client.headers['Authorization']='Bearer disconnected'
        assert client.get('/api/projects/apple_transfer').status_code==502
        response=client.put('/api/projects/apple_transfer/simulation',json={'adapter':'mock'})
        assert response.status_code==200,response.text
        assert client.get('/api/projects/apple_transfer').json()['adapter']=='mock'
        assert backend.tick_count==0


async def test_managed_scene_load_and_object_sync_are_authenticated_and_exclusive(store,model,instance):
    from shared.models.domain import WorldObject
    class ManagedContract(ContractCell):
        metadata={**ContractCell.metadata,'scene_loading':True,'scene_editing':True}
        loads=0
        def load_scene(self,request):self.loads+=1
        def sync_objects(self,objects):
            from simulation.isaac_sim.scene_assets import validate_objects
            validate_objects(objects);self.objects=objects
    objects=store.load_project('apple_transfer')[-1]
    backend=ManagedContract(model,instance,objects);worker=create_worker(backend,TOKEN)
    client=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker),base_url='http://worker',headers={'Authorization':f'Bearer {TOKEN}'})
    cell=IsaacCell('apple_transfer',[instance],backend.models,objects,client=client,require_native=False,load_scene=True)
    await cell.connect();assert backend.loads==1 and backend.tick_count==0
    added=WorldObject(id='box',name='Box',kind='obstacle',position={'x':1,'y':1,'z':.3},size={'x':.1,'y':.1,'z':.1})
    assert len((await cell.sync_objects([*objects,added])).objects)==len(objects)+1
    assert len((await cell.sync_objects(objects)).objects)==len(objects)
    await cell.advance({'arm_01':cell.latest.states['arm_01'].positions},1/30)
    with pytest.raises(WorkerUnavailable,match='Stop every robot'):await cell.sync_objects([added])
    assert backend.objects==objects
    await cell.stop()
    bad=added.model_copy(update={'id':'../bad'})
    with pytest.raises(WorkerUnavailable,match='Native object IDs'):await cell.sync_objects([bad])
    assert backend.objects==objects
    result=await client.post('/v1/sessions',json={'project_id':'other','robots':[],'objects':[],'load_scene':True})
    assert result.status_code==409 and backend.loads==1
    await cell.disconnect()


def test_desktop_remote_scene_edits_and_manual_controls_share_cell_ownership(store,model,instance):
    import yaml
    from services.api.main import create_app
    from simulation.isaac_sim.scene_assets import validate_objects
    class ManagedContract(ContractCell):
        metadata={**ContractCell.metadata,'scene_editing':True}
        def sync_objects(self,objects):validate_objects(objects);self.objects=objects
    backend=ManagedContract(model,instance,store.load_project('apple_transfer')[-1]);worker=create_worker(backend,TOKEN)
    path=store.project_folder('apple_transfer')/'project.yaml';project=yaml.safe_load(path.read_text());project['simulation']={'adapter':'isaac_sim'};path.write_text(yaml.safe_dump(project))
    app=create_app(store)
    def factory(pid,instances,models,objects):
        return IsaacCell(pid,instances,models,objects,client=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker),base_url='http://worker',headers={'Authorization':f'Bearer {TOKEN}'}),require_native=False)
    app.state.controller.remote_factory=factory
    with TestClient(app) as client:
        before=client.get('/api/projects/apple_transfer').json()
        added={'id':'box','name':'Box','kind':'obstacle','position':{'x':2,'y':2,'z':.2},'size':{'x':.1,'y':.1,'z':.1}}
        result=client.put('/api/projects/apple_transfer/world',json={'objects':[*before['objects'],added]})
        assert result.status_code==200,result.text
        assert any(o.id=='box' for o in backend.objects)
        controls=client.post('/api/projects/apple_transfer/controls',json={'robot_id':'arm_01','adapter_id':'isaac_sim','mode':'environment'})
        assert controls.status_code==201,controls.text
        sid=controls.json()['id']
        blocked=client.put('/api/projects/apple_transfer/world',json={'objects':before['objects']})
        assert blocked.status_code==422 and any(o.id=='box' for o in backend.objects)
        moved=client.post(f'/api/controls/{sid}/standard-command',json={'type':'SET_ACTUATOR','target':'base_yaw','value':.02,'unit':'rad'})
        assert moved.status_code==200,moved.text
        assert backend.states['arm_01'].positions['base_yaw']==pytest.approx(.02)
        assert backend.tick_count>0
        client.delete(f'/api/controls/{sid}')
        assert client.put('/api/projects/apple_transfer/world',json={'objects':before['objects']}).status_code==200
        assert not any(o.id=='box' for o in backend.objects)


async def test_managed_scene_replacement_keeps_lease_and_resets_requested_poses(store,model,instance):
    class ReloadableCell(ContractCell):
        def __init__(self,*args):
            super().__init__(*args)
            self.metadata={**self.metadata,'scene_loading':True}
            self.loads=0
        def load_scene(self,request):
            self.loads+=1
            self.models={r['instance']['instance']['id']:r['model'] for r in request.robots}
            self.objects=request.objects
    objects=store.load_project('apple_transfer')[-1]
    backend=ReloadableCell(model,instance,objects)
    app=create_worker(backend,TOKEN)
    client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://worker',headers={'Authorization':f'Bearer {TOKEN}'})
    cell=IsaacCell('apple_transfer',[instance],backend.models,objects,client=client,require_native=False)
    await cell.connect()
    lease=cell.session_id
    edited=copy.deepcopy(instance);edited['base_pose']=dict(x=.15,y=0.,z=0.,yaw=.2)
    models={'arm_01':with_base(model,edited)}
    body={'project_id':'other_project','robots':[{'instance':edited,'model':models['arm_01']}],'objects':[o.model_dump() for o in objects],'load_scene':True}
    response=await client.put(f'/v1/sessions/{lease}/scene',json=body)
    assert response.status_code==422 and backend.loads==0
    await cell.advance({'arm_01':{**cell.latest.states['arm_01'].positions,'base_yaw':.01}},1/30)
    body['project_id']='apple_transfer'
    assert (await client.put(f'/v1/sessions/{lease}/scene',json=body)).status_code==422
    assert backend.loads==0
    await cell.stop()
    q={**cell.latest.states['arm_01'].positions,'base_yaw':.1}
    await cell.reconfigure([edited],models,objects,{'arm_01':q})
    assert backend.loads==1 and cell.session_id==lease
    assert cell.latest.states['arm_01'].positions==q
    assert backend.models['arm_01']['base_pose']==edited['base_pose']
    assert [o.model_dump() for o in cell.latest.objects]==[o.model_dump() for o in objects]
    await cell.disconnect()


async def test_gpu_work_renews_idle_timer_but_state_and_health_polls_do_not(store,model,instance,tmp_path,monkeypatch):
    from services.api.storage import atomic_json
    import json
    monkeypatch.setenv('ROBOT_IDE_ACTIVITY_DIR',str(tmp_path))
    cell,backend,_=await connected(store,model,instance)
    path=tmp_path/'isaac.json';assert path.is_file()
    atomic_json(path,{'last_work':100})
    await cell.observe()
    await cell.client.get('/v1/health')
    assert json.loads(path.read_text())['last_work']==100
    q=cell.latest.states['arm_01'].positions
    await cell.advance({'arm_01':q},1/30)
    assert json.loads(path.read_text())['last_work']>100
    await cell.stop();await cell.disconnect()
