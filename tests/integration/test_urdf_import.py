import copy
import io
import json
import math
from pathlib import Path
import stat
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.ai_orchestrator.llm import LLMRegistry, ProviderConfiguration
from services.imports.urdf import parse_urdf
from services.validation.registry import ROOT

SOURCE=(ROOT/'examples/robots/bench_gantry.urdf').read_bytes()
BASE='/api/registry/urdf/drafts'


def upload(client, source=SOURCE, filename='gantry.urdf', suffix=''):
    response=client.post(BASE+f'?filename={filename}'+suffix,content=source,headers={'content-type':'application/octet-stream'})
    assert response.status_code==201,response.text
    return response.json()


def review(draft, **changes):
    return {'id':'imported_gantry','name':'Imported gantry','tool_link':'tool_tip',
        'joints':{j['name']:{'min':j['min'],'max':j['max'],'velocity':j['velocity'],'acceleration':.8,'initial':0}
                  for j in draft['parsed']['joints'] if j['type']!='fixed'},'reviewed':True,**changes}


def archive(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for name,data in files.items():z.writestr(name,data)
    return stream.getvalue()


def test_reviewed_urdf_import_is_not_registered_until_commit_and_source_survives(store):
    with TestClient(create_app(store)) as client:
        before=client.get('/api/projects/apple_transfer').json()
        d=upload(client);path=BASE+'/'+d['id'];settings=review(d)
        assert not (store.runtime/'imported_models/imported_gantry').exists()
        assert all(j['acceleration'] is None for j in d['parsed']['joints'])
        missing=copy.deepcopy(settings);missing['joints']['slide_x']['acceleration']=None
        assert 'needs configuration' in client.post(path+'/validate',json=missing).text
        missing['joints']['slide_x']['acceleration']=.8;missing['joints']['slide_x']['initial']=2
        assert 'initial position' in client.post(path+'/validate',json=missing).text
        checked=client.post(path+'/validate',json=settings)
        assert checked.status_code==200,checked.text
        bundle=checked.json()['bundle']
        assert checked.json()['planning_supported']
        assert bundle['actuators']['actuators']['slide_y']['unit']=='m'
        assert bundle['kinematics']['joints'][2]['axis_vector']==[0,-1,0]
        assert 'payload_unverified' in bundle['capabilities']['unsupported'] and bundle['capabilities']['operations']==['move_home']
        assert not (store.runtime/'imported_models/imported_gantry').exists()
        assert not list((store.runtime/'urdf_validation').glob('.import-*'))
        assert client.post(path+'/commit',json={**settings,'reviewed':False}).status_code==422
        result=client.post(path+'/commit',json=settings)
        assert result.status_code==201,result.text
        assert result.json()['source_import']['fields']['actuators.slide_x.min']=='urdf'
        assert result.json()['source_import']['fields']['actuators.slide_x.acceleration']=='user'
        assert client.get('/api/registry/imported_gantry/source').content==SOURCE
        assert client.get('/api/registry/imported_gantry/bundle').json()==bundle
        assert client.post(path+'/commit',json=settings).status_code==422
        assert client.get('/api/projects/apple_transfer').json()['fingerprint']==before['fingerprint'] # unused library additions do not invalidate a project
        assert client.get('/api/projects/apple_transfer').json()['instance']==before['instance']
        assert client.delete(path).status_code==200
        assert client.get(path).status_code==404
    with TestClient(create_app(store)) as client:
        assert client.get('/api/registry/imported_gantry/source').content==SOURCE
        assert any(m.get('source_import',{}).get('format')=='urdf' for m in client.get('/api/registry').json())


def test_imported_gantry_controls_and_ik_use_negative_axis_without_touching_project(store):
    with TestClient(create_app(store)) as client:
        d=upload(client);assert client.post(BASE+'/'+d['id']+'/commit',json=review(d)).status_code==201
        old=client.get('/api/projects/apple_transfer').json()
        session=client.post('/api/library/robots/imported_gantry/controls',json={'adapter_id':'mock','category':'virtual'})
        assert session.status_code==201,session.text
        sid=session.json()['id']
        try:
            result=client.post(f'/api/controls/{sid}/standard-command',json={'type':'MOVE_END_EFFECTOR','target':'tool','position':[.1,-.1,.35],'position_unit':'m','frame':'world'})
            assert result.status_code==200,result.text
            q=result.json()['feedback']['positions']
            assert q['slide_x']==pytest.approx(.1,abs=.002)
            assert q['slide_y']==pytest.approx(.1,abs=.002)
            assert q['slide_z']==pytest.approx(.07,abs=.002)
        finally:client.delete(f'/api/controls/{sid}')
        after=client.get('/api/projects/apple_transfer').json()
        assert after['instance']==old['instance'] and after['state']['positions']==old['state']['positions']


def test_packaged_source_mesh_resolution_and_original_download(store):
    urdf=SOURCE.replace(b'<link name="base_link"/>',b'<link name="base_link"><visual><geometry><mesh filename="package://gantry/meshes/base.obj"/></geometry></visual><collision><geometry><mesh filename="../meshes/base.obj"/></geometry></collision></link>')
    payload=archive({'gantry/urdf/robot.urdf':urdf,'gantry/meshes/base.obj':b'v 0 0 0\n'})
    with TestClient(create_app(store)) as client:
        d=upload(client,payload,'gantry.zip')
        assert all(m['status']=='retained' for m in d['meshes'])
        assert {m['path'] for m in d['meshes']}=={'gantry/meshes/base.obj'}
        assert client.post(BASE+'/'+d['id']+'/commit',json=review(d)).status_code==201
        assert client.get('/api/registry/imported_gantry/source').content==payload
        assert (store.runtime/'imported_models/imported_gantry/source/package/gantry/meshes/base.obj').is_file()


@pytest.mark.parametrize('bad',[
    b'<!DOCTYPE robot [<!ENTITY a "expanded">]><robot name="&a;"/>',
    b'<robot xmlns:xacro="http://ros.org/wiki/xacro" name="a"><xacro:include filename="file"/></robot>',
    b'<robot name="bad"><link name="a"/><link name="b"/></robot>',
    SOURCE.replace(b'axis xyz="1 0 0"',b'axis xyz="0 0 0"'),
    SOURCE.replace(b'lower="-0.5"',b'lower="nan"'),
    SOURCE.replace(b'parent link="base_link"',b'parent link="unknown"'),
    SOURCE.replace(b'name="tool_mount"',b'name="slide_x"'),
    b'<robot name="cycle"><link name="a"/><link name="b"/><joint name="ab" type="fixed"><parent link="a"/><child link="b"/></joint><joint name="ba" type="fixed"><parent link="b"/><child link="a"/></joint></robot>',
])
def test_bad_urdf_rejected_without_registering(store,bad):
    with TestClient(create_app(store)) as client:
        response=client.post(BASE+'?filename=bad.urdf',content=bad)
        assert response.status_code==422,response.text
        assert not list((store.runtime/'urdf_imports').glob('*/draft.json'))


@pytest.mark.parametrize('kind',['floating','planar'])
def test_unsupported_joint_types_and_mimic_are_explicit_blockers(store,kind):
    with TestClient(create_app(store)) as client:
        d=upload(client,SOURCE.replace(b'type="prismatic"',f'type="{kind}"'.encode(),1))
        assert d['parsed']['unsupported']
        assert client.post(BASE+'/'+d['id']+'/commit',json=review(d)).status_code==422
        d=upload(client,SOURCE.replace(b'<axis xyz="1 0 0"/>',b'<axis xyz="1 0 0"/><mimic joint="slide_y" multiplier="1"/>'))
        assert 'mimic' in d['parsed']['unsupported'][0]
        assert client.post(BASE+'/'+d['id']+'/commit',json=review(d)).status_code==422


def test_continuous_joint_requires_explicit_finite_control_window_and_preserves_type(store):
    source=SOURCE.replace(b'type="prismatic"',b'type="continuous"',1)
    with TestClient(create_app(store)) as client:
        d=upload(client,source);settings=review(d)
        assert settings['joints']['slide_x']['min'] is None
        assert client.post(BASE+'/'+d['id']+'/commit',json=settings).status_code==422
        settings['joints']['slide_x'].update(min=-math.pi,max=math.pi)
        result=client.post(BASE+'/'+d['id']+'/commit',json=settings)
        assert result.status_code==201,result.text
        assert result.json()['actuators']['actuators']['slide_x']['unit']=='rad'
        assert 'continuous' in client.get('/api/registry/imported_gantry/source').text


@pytest.mark.parametrize('files',[{'../escape.urdf':SOURCE},{'/absolute.urdf':SOURCE},{'C:/file.urdf':SOURCE},{'a\\b.urdf':SOURCE}])
def test_archive_path_traversal_rejected(store,files):
    with TestClient(create_app(store)) as client:
        assert client.post(BASE+'?filename=bad.zip',content=archive(files)).status_code==422


def test_archive_symlinks_duplicates_multiple_models_and_missing_meshes(store):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        item=zipfile.ZipInfo('link.urdf');item.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(item,'/private/file')
    with TestClient(create_app(store)) as client:
        assert client.post(BASE+'?filename=link.zip',content=stream.getvalue()).status_code==422
        payload=archive({'a.urdf':SOURCE,'b.urdf':SOURCE})
        assert 'selected' in client.post(BASE+'?filename=many.zip',content=payload).text
        assert upload(client,payload,'many.zip','&urdf_path=b.urdf')['urdf_path']=='b.urdf'
        d=upload(client,SOURCE.replace(b'<link name="base_link"/>',b'<link name="base_link"><visual><geometry><mesh filename="https://example.invalid/mesh.obj"/></geometry></visual></link>'))
        assert d['meshes'][0]['status']=='missing'
        assert any('missing' in w for w in client.post(BASE+'/'+d['id']+'/validate',json=review(d)).json()['provenance']['warnings'])


def test_llm_suggestions_are_advisory_and_never_change_extracted_values(store,monkeypatch):
    replies=[{'name':'Vendor gantry','manufacturer':'BenchCo','manufacturer_evidence':'BenchCo docs specify set_x for slide_x.','tool_link':'tool_tip','description':'A documented three-axis gantry.',
              'capability_suggestions':['Review suitability for inspection'],'command_mappings':[{'joint':'slide_x','vendor_command':'set_x(value)','evidence':'BenchCo docs specify set_x for slide_x.'}]}]
    calls=[];original=httpx.AsyncClient
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(replies[-1])}}]})
    monkeypatch.setattr('services.ai_orchestrator.llm.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    provider=LLMRegistry(store).save(ProviderConfiguration(name='Test LLM',base_url='http://llm.local/v1',model='test'))
    with TestClient(create_app(store)) as client:
        d=upload(client);path=BASE+'/'+d['id']
        suggested=client.post(path+'/suggest',json={'adapter_id':provider['id'],'documentation':'BenchCo docs specify set_x for slide_x.'})
        assert suggested.status_code==200,suggested.text
        assert suggested.json()['parsed']==d['parsed']
        assert 'system_prompt' not in suggested.json() and 'schema' in calls[0]['messages'][0]['content']
        settings=review(d,name='Vendor gantry',manufacturer='BenchCo')
        checked=client.post(path+'/validate',json=settings).json()
        assert checked['provenance']['fields']['robot.name']=='llm_suggestion_accepted'
        assert checked['bundle']['capabilities']['operations']==['move_home']
        assert checked['bundle']['capabilities']['payload_kg']==0
        settings['joints']['slide_x']['max']=999
        assert 'cannot be changed' in client.post(path+'/commit',json=settings).text
        for invalid in [{'tool_link':'made_up'}, {'actuators':{'slide_x':{'max':999}}}, {'manufacturer':'Undocumented'}]:
            replies.append(invalid)
            result=client.post(path+'/suggest',json={'adapter_id':provider['id']})
            assert result.status_code==422,result.text
            assert client.get(path).json()['parsed']==d['parsed']


def test_oblique_axis_forward_kinematics_preserves_joint_origin_and_direction():
    from services.planning.serial_ik import frames
    model={'kinematics':{'world_frame':'world','joints':[
        {'parent':'world','child':'joint','type':'revolute','actuator':'spin','axis_vector':[1,1,0],'origin':{'xyz':[0,0,.3]}},
        {'parent':'joint','child':'tip','type':'fixed','origin':{'xyz':[0,0,.2]}},
    ]}}
    tip=frames(model,{'spin':math.pi/2})['tip']
    assert [tip[i][3] for i in range(3)]==pytest.approx([math.sqrt(.02),-math.sqrt(.02),.3])


def test_root_frame_floor_exception_does_not_allow_nonroot_floor_contact(store):
    from services.imports.urdf import URDFImports,Review
    from services.api.model_library import ModelBundle,register_bundle
    from services.validation.trajectory import validate_trajectory
    from shared.models.domain import Frame
    importer=URDFImports(store,None)
    source=SOURCE.replace(b'xyz="0 0 0.2"',b'xyz="0 0 0"')
    draft=importer.create(source,'grounded.urdf')
    bundle,_=importer.build(draft['id'],Review.model_validate(review(draft)))
    model=register_bundle(store,ModelBundle.model_validate(bundle),activate=False)
    q={'slide_x':.1,'slide_y':0,'slide_z':0}
    with pytest.raises(ValueError,match='Link intersects table'):
        validate_trajectory(model,[Frame(time=t,step_id='floor_check',positions=q,objects={}) for t in [0,1]],[])


async def test_imported_robot_cartesian_plan_compiles_and_runs_without_a_gripper(store):
    import asyncio
    from services.api.model_library import ModelBundle,register_bundle
    from services.imports.urdf import URDFImports,Review
    from services.execution.controller import SimulationController
    from services.planning.definitions import compile_definition
    from services.api.storage import fingerprint
    from shared.models.domain import PlanDefinition,TaskDefinition,Pose
    runtime=SimulationController(store,speed=2000)
    importer=URDFImports(store,runtime.llm);draft=importer.create(SOURCE,'gantry.urdf')
    bundle,_=importer.build(draft['id'],Review.model_validate(review(draft)))
    register_bundle(store,ModelBundle.model_validate(bundle))
    # Add the imported model beside the existing arm using the real instance API.
    app=create_app(store)
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
        added=await c.post('/api/projects/apple_transfer/robots',json={'id':'gantry','name':'Gantry','model_id':'imported_gantry','base_pose':{'x':0,'y':2,'z':0,'yaw':0}})
        assert added.status_code==201,added.text
    *_,session,_=await runtime.context('apple_transfer')
    definition=PlanDefinition(id='gantry_pose',project_id='apple_transfer',name='Gantry pose',tasks=[TaskDefinition(id='move',name='Move tool',robot_id='gantry',operation='move',target=Pose(x=.1,y=1.9,z=.35))])
    snapshot=await runtime.snapshot('apple_transfer')
    plan=compile_definition(definition,session.instances,session.models,session.objects,await runtime.states(session),fingerprint(snapshot),'mock')
    assert plan.valid,[(c.id,c.message) for c in plan.checks]
    store.save_definition(definition);store.save_plan(plan,snapshot)
    run=await runtime.execute_registered_plan(plan.id,plan.fingerprint,'apple_transfer')
    await asyncio.wait_for(runtime.jobs[run.id],10)
    assert run.status=='SIMULATION_PASSED',run.logs
    assert (await runtime.states(session))['gantry'].positions['slide_y']==pytest.approx(.1,abs=.002)
    await runtime.close()
