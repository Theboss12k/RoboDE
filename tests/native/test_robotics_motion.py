"""Opt-in real Linux MoveIt/Nav2 tests. No Isaac or hardware is involved."""
import base64,copy,os
from pathlib import Path
import pytest
from services.api.storage import Storage,atomic_json
from services.validation.registry import ROOT
from services.imports.urdf import URDFImports,Review
from services.api.model_library import register_bundle,ModelBundle
from services.ai_orchestrator.llm import LLMRegistry
from services.planning.motion_client import MotionClient
pytestmark=pytest.mark.skipif(os.getenv('ROBOT_DE_NATIVE_TESTS')!='1',reason='Opt-in local Linux robotics container required')

@pytest.fixture
def native(tmp_path):
    store=Storage(tmp_path);imports=URDFImports(store,LLMRegistry(store));source=(ROOT/'examples/robots/bench_gantry.urdf').read_text()
    source=source.replace('<link name="base_link"/>','<link name="base_link"><collision><origin xyz="0 0 0.05"/><geometry><box size="0.08 0.08 0.1"/></geometry></collision></link>').replace('<link name="tool_tip"/>','<link name="tool_tip"><collision><geometry><box size="0.02 0.02 0.02"/></geometry></collision></link>')
    draft=imports.create(source.encode(),'gantry.urdf');review=Review(id='native_gantry',name='Native gantry',tool_link='tool_tip',reviewed=True,joints={j['name']:{'min':j['min'],'max':j['max'],'velocity':j['velocity'],'acceleration':.8,'initial':0.} for j in draft['parsed']['joints'] if j['type']!='fixed'})
    bundle,provenance=imports.build(draft['id'],review);model=register_bundle(store,ModelBundle.model_validate(bundle),source=(imports.folder(draft['id']),provenance))
    atomic_json(store.runtime/'connections/motion.json',{'url':'http://127.0.0.1:9120','token_env':'ROBOT_DE_NATIVE_TOKEN'})
    token=ROOT/'robot_system/runtime/connections/motion.token';(store.runtime/'connections/motion.token').write_text(token.read_text());(store.runtime/'connections/motion.token').chmod(0o600)
    client=MotionClient(store);body={'robot':client.model_payload(model),'positions':{'slide_x':0.,'slide_y':0.,'slide_z':0.},'base_pose':{'x':0.,'y':0.,'z':0.,'yaw':0.},'goal':{'kind':'joint','joint':'slide_x','value':.05},'objects':[]}
    return client,body

def frames(path):return [{'time':s['time'],'positions':s['positions'],'robot_positions':{'gantry':s['positions']},'base_poses':{'gantry':s['base_pose']},'objects':{},'held_objects':{'gantry':None},'active_steps':{'gantry':'move'}} for s in path['samples']]

async def test_native_joint_and_tool_ik_and_unreachable(native):
    client,body=native;planned=await client.request('/v2/plan',body)
    assert planned['samples'][-1]['positions']['slide_x']==pytest.approx(.05,abs=1e-6)
    body['goal']={'kind':'tool','target':'tool','position':[.1,.05,.35],'frame':'world'}
    tool=await client.request('/v2/plan',body);assert tool['samples'][-1]['positions']['slide_z']==pytest.approx(.07,abs=.001)
    body['goal']['position']=[50.,50.,50.]
    with pytest.raises(ValueError,match='IK'):await client.request('/v2/plan',body)

async def test_native_swept_checks_and_collision_between_endpoints(native):
    client,body=native;path=await client.request('/v2/plan',body);timeline=frames(path)
    clear=await client.request('/v2/validate',{'robots':{'gantry':body['robot']},'frames':timeline,'objects':[]})
    assert clear['status']=='passed',clear
    obstacle={'id':'thin','name':'Thin obstacle','kind':'obstacle','position':{'x':.025,'y':0.,'z':.28},'size':{'x':.002,'y':.02,'z':.02},'mass_kg':0.,'mesh':None}
    collision=await client.request('/v2/validate',{'robots':{'gantry':body['robot']},'frames':[timeline[0],timeline[-1]],'objects':[obstacle]})
    assert collision['status']=='failed' and any('between' in f['message'] for f in collision['findings']),collision
    imported={**obstacle,'id':'mesh_payload','mesh':{'format':'glb'}}
    held=copy.deepcopy(timeline)
    for frame in held:frame.update(held_objects={'gantry':'mesh_payload'},held_tools={'gantry':'tool'})
    unsupported=await client.request('/v2/validate',{'robots':{'gantry':body['robot']},'frames':held,'objects':[imported]})
    assert unsupported['status']=='incomplete' and any(f['code']=='UNSUPPORTED_ASSET_GEOMETRY' for f in unsupported['findings']),unsupported

async def test_native_rover_navigation(native):
    client,body=native;model=body['robot']['model'];model['mobility']={'classification':'MOVING','left_wheel':'left','right_wheel':'right','wheel_radius_m':.05,'track_width_m':.3,'max_linear_m_s':.2,'max_angular_rad_s':.5,'footprint':[[-.1,-.1],[.1,-.1],[.1,.1],[-.1,.1]],'navigation_bounds':[-2.,-2.,2.,2.]}
    model['actuators']['actuators']={name:{'type':'revolute','unit':'rad','min':-1000.,'max':1000.,'velocity':10.,'acceleration':20.} for name in ('left','right')}
    body.update(positions={'left':0.,'right':0.},goal={'kind':'base','position':[.3,.2],'yaw':.1})
    path=await client.request('/v2/plan',body);last=path['samples'][-1]['base_pose'];assert last['x']==pytest.approx(.3) and last['y']==pytest.approx(.2) and last['yaw']==pytest.approx(.1)

async def test_native_mobile_manipulator_priorities_and_stopped_base_stage(native):
    import hashlib
    client,body=native;payload=body['robot'];model=payload['model'];urdf_path=payload['urdf_path']
    source=base64.b64decode(payload['files'][urdf_path]).decode()
    wheel_xml=''.join(f'<link name="{side}_link"/><joint name="{side}" type="continuous"><parent link="base_link"/><child link="{side}_link"/><axis xyz="0 1 0"/><origin xyz="0 {sign*.15} 0"/><limit effort="10" velocity="10"/></joint>' for side,sign in [('left',1),('right',-1)])
    source=source.replace('</robot>',wheel_xml+'</robot>');raw=source.encode();payload['files'][urdf_path]=base64.b64encode(raw).decode();model['source_import']['sha256']=hashlib.sha256(raw).hexdigest()
    model['actuators']['actuators'].update({name:{'type':'revolute','unit':'rad','min':-1000.,'max':1000.,'velocity':10.,'acceleration':20.} for name in ('left','right')})
    model['continuous_joints']=['left','right'];body['positions'].update(left=0.,right=0.)
    model['mobility']={'classification':'BOTH','priority':'arm_first','left_wheel':'left','right_wheel':'right','wheel_radius_m':.05,'track_width_m':.3,'max_linear_m_s':.2,'max_angular_rad_s':.5,'footprint':[[-.1,-.1],[.1,-.1],[.1,.1],[-.1,.1]],'navigation_bounds':[-2.,-2.,2.,2.],'transit_positions':dict(body['positions'])}
    body['goal']={'kind':'tool','target':'tool','position':[.1,.05,.35],'frame':'world'}
    stationary=await client.request('/v2/plan',body)
    assert stationary['engine']=='MoveIt2/OMPL' and stationary['samples'][-1]['base_pose']['x']==0
    model['mobility']['priority']='base_first'
    staged=await client.request('/v2/plan',body)
    assert staged['stages']==['transit','base','stop','arm']
    assert staged['samples'][-1]['base_pose']['x']!=0
    assert all(b['time']>a['time'] for a,b in zip(staged['samples'],staged['samples'][1:]))
