"""Physical authorization tests use injected feedback, never robot hardware."""
import asyncio
from datetime import datetime,timezone,timedelta
import pytest
from workers.robotics.physical import PhysicalRuntime
from services.api.storage import fingerprint

class Process:
    def __init__(self):self.values={'joint':.1};self.calls=[]
    async def request(self,body):
        self.calls.append(body)
        if body['operation']=='command':self.values.update({c['function']:c['value'] for c in body['commands']})
        return {'source':'hardware','device_id':'fixture-device','connected':True,'stopped':True,'measured_at':datetime.now(timezone.utc).isoformat(),'positions':dict(self.values),'velocities':{'joint':0.}}
    async def close(self):pass

def runtime():
    rt=PhysicalRuntime();process=Process()
    rt.connections['fixture']={'process':process,'device_id':'fixture-device','touched':__import__('time').monotonic(),'driver_hash':'driver','binding_hash':'binding','qualified_functions':{'joint'},'bundle':{'definition':{'functions':[{'id':'joint','mode':'position','minimum':-1.,'maximum':1.}]}},'state':{'positions':{'joint':.1},'stopped':True}}
    return rt,process

def body():return {'binding':{'hash':'binding','driver_hash':'driver','definition':{'joints':[{'joint_id':'j','function_id':'joint','role':'independent','scale':1.,'offset':0.}]}},'frames':[{'time':0.,'positions':{'j':.1}},{'time':.02,'positions':{'j':.15}}],'revision_id':'immutable-revision','validation':{'status':'passed','hardware_validated':False},'remaining_seconds':600,'hardware_motion_reviewed':True,'operator_acknowledgement':'Arm this exact physical revision'}

async def test_physical_authorization_is_revision_bound_expiring_and_one_use():
    rt,p=runtime();data=body();a=await rt.arm('fixture',data)
    assert a['revision_id']==data['revision_id'] and a['expires_in']==30
    result=await rt.execute('fixture',a['authorization']);await rt.runs[result['id']]['job']
    assert rt.runs[result['id']]['status']=='completed' and rt.runs[result['id']]['stopped_verified']
    with pytest.raises(ValueError,match='already consumed'):await rt.execute('fixture',a['authorization'])
    a=await rt.arm('fixture',{**data,'frames':[{'time':0.,'positions':{'j':.15}},{'time':.02,'positions':{'j':.2}}]})
    rt.authorizations[a['authorization']]['expires']=0
    with pytest.raises(ValueError,match='expired'):await rt.execute('fixture',a['authorization'])

async def test_incomplete_cloud_window_stale_state_and_invalid_batch_block():
    rt,p=runtime();data=body()
    for patch,match in [({'validation':{'status':'incomplete'}},'complete'),({'remaining_seconds':60},'remaining'),({'operator_acknowledgement':''},'Explicit'),({'hardware_motion_reviewed':False},'review')]:
        with pytest.raises(ValueError,match=match):await rt.arm('fixture',{**data,**patch})
    data['frames'][1]['positions']['j']=99
    with pytest.raises(ValueError,match='limits'):await rt.arm('fixture',data)
    assert all(c['operation']!='command' for c in p.calls)
    data=body();data['frames'][0]['positions']['j']=.5
    with pytest.raises(ValueError,match='starting state'):await rt.arm('fixture',data)

async def test_stop_invalidates_arming_and_reports_confirmed_feedback_separately():
    rt,p=runtime();a=await rt.arm('fixture',body());result=await rt.stop('fixture')
    assert result['stop_requested'] and result['stopped_verified']
    with pytest.raises(ValueError):await rt.execute('fixture',a['authorization'])
    state=await rt.heartbeat('fixture');state['measured_at']=(datetime.now(timezone.utc)-timedelta(seconds=4)).isoformat()
    with pytest.raises(ValueError,match='stale'):rt.require_feedback(state,'fixture-device')
    with pytest.raises(ValueError,match='identify'):rt.require_feedback({**state,'source':'simulation'},'fixture-device')

async def test_simulation_success_cannot_qualify_hardware_execution():
    rt,p=runtime();rt.connections['fixture']['qualified_functions']=set()
    with pytest.raises(ValueError,match='every independent actuator'):await rt.arm('fixture',body())
    request=body();request['purpose']='actuator_qualification';request['frames'][1]['positions']['j']=.11
    armed=await rt.arm('fixture',request);started=await rt.execute('fixture',armed['authorization']);await rt.runs[started['id']]['job']
    assert rt.connections['fixture']['qualified_functions']=={'joint'}

async def test_mobile_start_requires_matching_measured_odometry_before_movement():
    rt,p=runtime();data=body();data['binding']['definition']['mobility']={'classification':'MOVING'}
    for frame in data['frames']:frame['base_pose']={'x':0.,'y':0.,'yaw':0.}
    with pytest.raises(ValueError,match='measured odometry'):await rt.arm('fixture',data)
    rt.connections['fixture']['state']['base_pose']={'x':.1,'y':0.,'yaw':0.}
    with pytest.raises(ValueError,match='starting base pose'):rt.batches(data,rt.connections['fixture'])
    rt.connections['fixture']['state']['base_pose']={'x':0.,'y':0.,'yaw':0.}
    assert len(rt.batches(data,rt.connections['fixture']))==2
    assert all(c['operation']!='command' for c in p.calls)


def test_physical_task_success_requires_measured_attachment_and_object_pose():
    from shared.models.domain import WorldObject,Pose
    rt,p=runtime();check={'kind':'grasp','object_id':'apple','task_id':'grasp'}
    with pytest.raises(ValueError,match='measured hardware'):rt.verify_postcondition(check,{'positions':{'joint':0.}})
    state={'attachment_source':'hardware_sensor','attachments':['apple'],'positions':{'joint':.1}}
    rt.verify_postcondition(check,state)
    release={**check,'kind':'release','gripper_function':'joint','gripper_open':.1}
    with pytest.raises(ValueError,match='attachment'):rt.verify_postcondition(release,state)
    state['attachments']=[];rt.verify_postcondition(release,state)
    obj=WorldObject(id='apple',name='Apple',kind='object',position=Pose(x=0,y=0,z=.1),size=Pose(x=.02,y=.02,z=.02),mass_kg=.1)
    target=WorldObject(id='basket',name='Basket',kind='region',position=Pose(x=0,y=0,z=.1),size=Pose(x=.2,y=.2,z=.2),mass_kg=0.)
    verify={**check,'kind':'verify','object':obj.model_dump(),'target':target.model_dump()}
    with pytest.raises(ValueError,match='measured object pose'):rt.verify_postcondition(verify,state)
    state['objects']={'apple':{'x':.5,'y':0.,'z':.1}}
    with pytest.raises(ValueError,match='placement'):rt.verify_postcondition(verify,state)
    state['objects']['apple']['x']=0.;rt.verify_postcondition(verify,state)
