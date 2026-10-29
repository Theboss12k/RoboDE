import copy
import json
import math
import pytest
from fastapi.testclient import TestClient
from shared.models.command import StandardCommand
from shared.models.domain import TaskDefinition,PlanDefinition,RobotState
from services.commands.standard import resolve_command
from services.planning.serial_ik import inverse_pose,effector_frame,rotation_error,transform
from services.planning.definitions import compile_definition
from services.api.main import create_app


async def test_task_draft_repairs_schema_once_but_never_repairs_unknown_targets(model,instance):
    from types import SimpleNamespace
    from services.ai_orchestrator.task_drafting import draft_tasks
    calls=[]
    pose={'id':'pose','name':'Move tool','operation':'command','robot_id':'arm_01','command':{
        'type':'MOVE_END_EFFECTOR','target':'parallel_gripper','position':[.35,-.1,.3],'frame':'world'}}
    async def invoke(goal,system):
        calls.append((goal,system))
        task=copy.deepcopy(pose)
        if len(calls)>1:task['command']['position_unit']='m'
        return {'answer':json.dumps({'tasks':[task]})}
    registry=SimpleNamespace(adapter=lambda _:invoke)
    positions=instance['initial_configuration']['actuator_positions']
    tasks=await draft_tasks(registry,None,'Move tool to the requested world position',model,'arm_01',[],positions)
    assert len(calls)==2 and tasks[0].command.position_unit=='m'
    assert json.loads(calls[1][0])['original_goal']=='Move tool to the requested world position'
    calls.clear()
    async def unknown(goal,system):
        calls.append(goal)
        return {'answer':json.dumps({'tasks':[{'id':'unknown','name':'Unknown actuator','operation':'command','robot_id':'arm_01',
            'command':{'type':'SET_ACTUATOR','target':'tail_motor','value':.5,'unit':'rad'}}]})}
    registry.adapter=lambda _:unknown
    with pytest.raises(ValueError,match='Unknown actuator'):
        await draft_tasks(registry,None,'Move tail_motor',model,'arm_01',[],positions)
    assert len(calls)==1


async def test_task_draft_schema_repair_is_bounded(model,instance):
    from types import SimpleNamespace
    from services.ai_orchestrator.task_drafting import draft_tasks
    calls=[]
    async def malformed(goal,system):
        calls.append(goal)
        return {'answer':'{"tasks":'}
    with pytest.raises(ValueError,match='valid capability-compatible task draft'):
        await draft_tasks(SimpleNamespace(adapter=lambda _:malformed),None,'Move tool',model,'arm_01',[],instance['initial_configuration']['actuator_positions'])
    assert len(calls)==2


@pytest.mark.parametrize('offset,expected',[(.1,422),(.3,200)])
def test_llm_relative_lift_verifies_compiled_result_before_saving(store,monkeypatch,offset,expected):
    import uuid
    from services.ai_orchestrator.llm import ProviderConfiguration
    app=create_app(store)
    app.state.llm.save(ProviderConfiguration(name='Grounded test',base_url='http://test.invalid/v1',model='test'))
    item=next(o for o in store.load_project('apple_transfer')[3] if o.id=='apple')
    tasks=[{'id':'approach','name':'Reach apple','robot_id':'arm_01','operation':'command','command':{
        'type':'MOVE_END_EFFECTOR','target':'parallel_gripper','position':list(item.position.model_dump().values()),'position_unit':'m','frame':'world'}},
        {'id':'grasp','name':'Grasp apple','robot_id':'arm_01','operation':'grasp','object_id':'apple','dependencies':['approach']},
        {'id':'lift','name':'Lift apple','robot_id':'arm_01','operation':'command','dependencies':['grasp'],'command':{
        'type':'MOVE_END_EFFECTOR','target':'parallel_gripper','position':[item.position.x,item.position.y,item.position.z+offset],'position_unit':'m','frame':'world'}}]
    async def invoke(*_):return {'answer':json.dumps({'tasks':tasks})}
    monkeypatch.setattr(app.state.llm,'adapter',lambda *_:invoke)
    goal='Pick up the apple and hold it 30 cm directly above its current position. Do not release it.'
    with TestClient(app) as client:
        definition=client.post('/api/projects/apple_transfer/plan-definitions',json={'name':'Lift','goal':goal}).json()
        path=f"/api/projects/apple_transfer/plan-definitions/{definition['id']}"
        response=client.post(path+'/draft',json={'version':1,'goals':[{'id':'lift','robot_id':'arm_01','prompt':goal}]})
        assert response.status_code==expected,response.text
        if expected==422:
            assert 'requested object lift' in response.text
            assert client.get(path).json()['tasks']==[] and client.get(path).json()['version']==1
        business=client.post('/api/business/projects/apple_transfer/commands',json={'request_id':str(uuid.uuid4()),'instruction':goal})
        assert business.status_code==(201 if expected==200 else 422),business.text
        assert not app.state.controller.leases


def cartesian(model):
    m=copy.deepcopy(model)
    m['actuators']['actuators']={k:{'type':'prismatic','min':-1.,'max':1.,'unit':'m','velocity':.5,'acceleration':1.} for k in ('slide_x','slide_y','slide_z')}
    m['kinematics']={'solver':'serial_chain_dls_v1','world_frame':'world','units':'m','links':{'tool':.01},'joints':[
        {'actuator':'slide_x','parent':'world','child':'x','type':'prismatic','axis':'x','origin':{'xyz':[0.,0.,.2]}},
        {'actuator':'slide_y','parent':'x','child':'y','type':'prismatic','axis':'y'},
        {'actuator':'slide_z','parent':'y','child':'tool','type':'prismatic','axis':'z'}],
        'end_effectors':{'tool_1':{'link':'tool'}}}
    m['capabilities']['components']={}
    return m


def test_direct_commands_do_not_invoke_ik(model,instance,monkeypatch):
    import services.commands.standard as standard
    monkeypatch.setattr(standard,'inverse',lambda *args:pytest.fail('Direct command invoked IK'))
    current=instance['initial_configuration']['actuator_positions']
    result=resolve_command(model,current,{'type':'SET_ACTUATOR','target':'elbow','value':-.9,'unit':'rad'})
    assert result['elbow']==-.9 and result['shoulder']==current['shoulder']
    assert resolve_command(model,current,{'type':'SET_COMPONENT','target':'parallel_gripper','value':50.,'unit':'percent'})['gripper']==.04
    for command in [dict(type='SET_ACTUATOR',target='elbow',value=40.,unit='rad'),dict(type='SET_ACTUATOR',target='elbow',value=0.,unit='m'),dict(type='SET_COMPONENT',target='missing',value=50.,unit='percent'),dict(type='SET_COMPONENT',target='parallel_gripper',value=101.,unit='percent')]:
        with pytest.raises(ValueError):resolve_command(model,current,command)
    with pytest.raises(ValueError):StandardCommand(type='SET_ACTUATOR',target='elbow',value=True,unit='rad')


def test_pose_ik_reachable_unreachable_orientation_and_named_effectors(model):
    m=cartesian(model);seed={k:0. for k in m['actuators']['actuators']}
    command={'type':'MOVE_END_EFFECTOR','target':'tool_1','position':[.3,.2,.5],'position_unit':'m','frame':'world'}
    q=resolve_command(m,seed,command)
    assert [effector_frame(m,q,'tool_1')[i][3] for i in range(3)]==pytest.approx([.3,.2,.5],abs=.0005)
    with pytest.raises(ValueError,match='unreachable'):resolve_command(m,seed,{**command,'position':[3.,0.,0.]})
    with pytest.raises(ValueError,match='unreachable'):resolve_command(m,seed,{**command,'orientation_rpy':[0.,0.,math.pi],'orientation_unit':'rad'})
    with pytest.raises(ValueError,match='end effector'):resolve_command(m,seed,{**command,'target':'tool_2'})
    with pytest.raises(ValueError,match='frame'):resolve_command(m,seed,{**command,'frame':'camera'})
    assert math.sqrt(sum(v*v for v in rotation_error(transform(rpy=[0,0,math.pi]),transform())))==pytest.approx(math.pi)


def test_multi_effector_ik_does_not_move_other_arm(model):
    m=cartesian(model);m['actuators']['actuators']['other']=copy.deepcopy(m['actuators']['actuators']['slide_x'])
    m['kinematics']['joints'].append({'actuator':'other','parent':'world','child':'other_tool','type':'prismatic','axis':'x','origin':{'xyz':[0.,.6,.3]}})
    m['kinematics']['end_effectors']['tool_2']={'link':'other_tool'}
    q=inverse_pose(m,[.2,.6,.3],None,dict.fromkeys(m['actuators']['actuators'],0.),'tool_2')
    assert q['other']==pytest.approx(.2,abs=.0005)
    assert q['slide_x']==q['slide_y']==q['slide_z']==0


async def test_direct_task_on_model_without_ik_compiles_and_runs(store,model):
    from services.execution.controller import SimulationController
    from services.api.storage import fingerprint
    load=store.load_project
    def configuration_only(pid):
        project,instances,models,objects=load(pid)
        for model in models:model['kinematics']['solver']='configuration_only'
        return project,instances,models,objects
    store.load_project=configuration_only
    controller=SimulationController(store,speed=500)
    _,_,_,session,_=await controller.context('apple_transfer')
    states=await controller.states(session)
    definition=PlanDefinition(id='standard',project_id='apple_transfer',name='Direct',tasks=[TaskDefinition(id='joint',name='Move elbow',operation='command',robot_id='arm_01',command=StandardCommand(type='SET_ACTUATOR',target='elbow',value=-1.6,unit='rad'))])
    snapshot=await controller.snapshot('apple_transfer')
    revision=compile_definition(definition,session.instances,session.models,session.objects,states,fingerprint(snapshot),'mock')
    assert revision.valid and any(c.id=='geometry_scope' for c in revision.checks)
    store.save_definition(definition);store.save_plan(revision,snapshot)
    run=await controller.execute_registered_plan(revision.id,revision.fingerprint,'apple_transfer')
    await controller.jobs[run.id]
    assert run.status=='SIMULATION_PASSED'
    assert run.robot_states['arm_01'].positions['elbow']==-1.6
    await controller.close()


def test_llm_drafting_gets_contract_and_returns_reviewable_tasks(store,monkeypatch):
    app=create_app(store);seen=[]
    from services.ai_orchestrator.llm import ProviderConfiguration
    profile=app.state.llm.save(ProviderConfiguration(name='Task LLM',base_url='https://test.invalid/v1',model='test'))
    async def invoke(goal,system):
        seen.append((goal,system))
        return {'answer':json.dumps({'tasks':[{'id':'joint','name':'Move elbow','operation':'command','robot_id':'arm_01','command':{'type':'SET_ACTUATOR','target':'elbow','unit':'rad','value':-1.6}}]})}
    monkeypatch.setattr(app.state.llm,'adapter',lambda *_:invoke)
    with TestClient(app) as client:
        definition=client.post('/api/projects/apple_transfer/plan-definitions',json={'name':'Generated'}).json()
        result=client.post(f'/api/projects/apple_transfer/plan-definitions/{definition["id"]}/draft',json={'version':1,'adapter_id':profile['id'],'goals':[{'id':'goal','robot_id':'arm_01','prompt':'Move the elbow to -1.6 radians'}]})
        assert result.status_code==200,result.text
        task=result.json()['tasks'][0]
        assert task['operation']=='command' and task['command']['unit']=='rad'
        assert 'CURRENT_JOINTS=' in seen[0][1] and 'bypasses IK' in seen[0][1] and 'MOVE_END_EFFECTOR' in seen[0][1]
        assert app.state.controller.leases=={}
        assert client.post(f'/api/projects/apple_transfer/plan-definitions/{definition["id"]}/compile').json()['valid']


def test_revolute_pose_ik_and_fixed_tool_transform(model):
    m=copy.deepcopy(model)
    m['actuators']['actuators']={key:{'type':'revolute','unit':'rad','min':-2.,'max':2.,'velocity':1.,'acceleration':2.} for key in ('a','b')}
    m['kinematics']={'solver':'serial_chain_dls_v1','world_frame':'world','units':'m','links':{'arm':.3},'joints':[
        {'actuator':'a','parent':'world','child':'arm','axis':'z','type':'revolute','origin':{'xyz':[0.,0.,.2]}},
        {'actuator':'b','parent':'arm','child':'forearm','axis':'z','type':'revolute','origin':{'xyz':[.3,0.,0.]}},
        {'parent':'forearm','child':'tool','type':'fixed','origin':{'xyz':[.2,0.,0.]}}],
        'end_effectors':{'hand':{'link':'tool'}}}
    wanted=effector_frame(m,{'a':.4,'b':-.3},'hand')
    q=inverse_pose(m,[wanted[i][3] for i in range(3)],[0.,0.,.1],{'a':0.,'b':0.},'hand')
    actual=effector_frame(m,q,'hand')
    assert [actual[i][3] for i in range(3)]==pytest.approx([wanted[i][3] for i in range(3)],abs=.0005)
    assert rotation_error(wanted,actual)==pytest.approx([0.,0.,0.],abs=.002)


async def test_apple_lift_tasks_compile_without_releasing_object(store):
    from services.execution.controller import SimulationController
    from services.planning.kinematics import inverse
    c=SimulationController(store);_,_,_,s,_=await c.context('apple_transfer')
    def pose(x,y,z):return StandardCommand(type='MOVE_END_EFFECTOR',target='parallel_gripper',position=[x,y,z],position_unit='m',frame='world')
    tasks=[TaskDefinition(id='approach',name='Approach apple',operation='command',robot_id='arm_01',command=pose(.34,-.16,.065)),
        TaskDefinition(id='grasp',name='Grasp apple',operation='grasp',robot_id='arm_01',object_id='apple',dependencies=['approach']),
        TaskDefinition(id='lift',name='Lift apple by 30 cm',operation='command',robot_id='arm_01',dependencies=['grasp'],command=pose(.34,-.16,.365))]
    definition=PlanDefinition(id='lift',project_id='apple_transfer',name='Lift',tasks=tasks)
    revision=compile_definition(definition,s.instances,s.models,s.objects,await c.states(s),'test','mock')
    assert revision.valid,revision.checks
    assert revision.frames[-1].held_objects['arm_01']=='apple'
    assert revision.frames[-1].objects['apple'].z==pytest.approx(.365)
    await c.close()
