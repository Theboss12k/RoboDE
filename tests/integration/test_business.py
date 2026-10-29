import copy
import time
import uuid
import yaml
from fastapi.testclient import TestClient
from services.api.main import create_app


def tables(store):
    path=store.project_folder('apple_transfer')/'environment/world.yaml'
    world=yaml.safe_load(path.read_text())
    world['objects']=[dict(id='apple',name='Apple',kind='object',position=dict(x=.34,y=-.16,z=.0525),size=dict(x=.065,y=.065,z=.065),mass_kg=.08),
        dict(id='table1',name='Table1',kind='obstacle',position=dict(x=.34,y=-.16,z=.01),size=dict(x=.14,y=.14,z=.02),mass_kg=0),
        dict(id='table2',name='Table2',kind='obstacle',position=dict(x=.27,y=.27,z=.01),size=dict(x=.18,y=.18,z=.02),mass_kg=0)]
    path.write_text(yaml.safe_dump(world))


def test_business_table_transfer_shared_engine_review_idempotency_and_run(store):
    tables(store)
    with TestClient(create_app(store,speed=1000)) as client:
        base='/api/business/projects/apple_transfer'
        workspace=client.get(base+'/workspace').json()
        assert {a['name'] for a in workspace['assets']} >= {'Apple','Table1','Table2'}
        data={'instruction':'MOVE APPLE FROM TABLE1 TO TABLE2','request_id':str(uuid.uuid4())}
        prepared=client.post(base+'/commands',json=data)
        assert prepared.status_code==201,prepared.text
        job=prepared.json();assert job['status']=='ready' and job['run_id'] is None
        assert len(job['steps'])==9
        revision=store.get_plan('apple_transfer',job['revision_id'])
        assert revision.valid and all(t.placement=='on_surface' for t in revision.atomic_tasks)
        assert all(t.robot_id=='arm_01' for t in revision.atomic_tasks)
        assert not store.list_runs('apple_transfer')
        assert client.post(base+'/commands',json=data).json()['id']==job['id']
        assert len(store.list_definitions('apple_transfer'))==1
        assert client.post(base+'/commands',json={**data,'instruction':'Move home'}).status_code==409
        running=client.post(base+'/commands/'+job['id']+'/run')
        assert running.status_code==202,running.text
        for _ in range(200):
            progress=client.get(base+'/commands/'+job['id']+'/run').json()
            if progress['finished_at']:break
            time.sleep(.01)
        assert progress['status']=='SIMULATION_PASSED',progress
        after=client.get(base+'/workspace').json()
        item=next(o for o in after['objects'] if o['id']=='apple')
        assert abs(item['position']['x']-.27)<.001
        assert abs(item['position']['z']-.0525)<.001
        assert client.post(base+'/commands/'+job['id']+'/run').json()['run_id']==running.json()['run_id']


def test_business_unknown_source_ambiguous_assets_and_stale_plan_do_not_execute(store):
    tables(store)
    with TestClient(create_app(store)) as client:
        base='/api/business/projects/apple_transfer'
        for text in ['Move Apple from Table2 to Table1','Move Banana from Table1 to Table2','Move Apple from Table1 to Missing','Do not move Apple from Table1 to Table2']:
            response=client.post(base+'/commands',json={'instruction':text,'request_id':str(uuid.uuid4())})
            assert response.status_code==422,response.text
        assert not store.list_runs('apple_transfer')
        prepared=client.post(base+'/commands',json={'instruction':'Move Apple from Table1 to Table2','request_id':str(uuid.uuid4())}).json()
        client.post('/api/projects/apple_transfer/reset')
        # Configuration changes must invalidate the business revision just as IDE revisions.
        client.put('/api/projects/apple_transfer/robots/arm_01/placement',json=dict(x=.03,y=0.,z=0.,yaw=0.))
        result=client.post(base+'/commands/'+prepared['id']+'/run')
        assert result.status_code==409
        assert not store.list_runs('apple_transfer')
