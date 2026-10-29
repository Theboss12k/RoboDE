import copy
from fastapi.testclient import TestClient
from services.api.main import create_app


def bundle(client,id='custom_arm'):
    result=client.get('/api/registry/demo_arm/bundle').json()
    result['robot'].update(id=id,name='Custom educational arm')
    return result


def test_import_and_add_instance_preserves_model_and_existing_measured_state(store):
    with TestClient(create_app(store)) as client:
        original=client.get('/api/projects/apple_transfer').json()
        data=bundle(client)
        imported=client.post('/api/registry/import',json=data)
        assert imported.status_code==201,imported.text
        assert imported.json()['planning_supported']
        assert {m['robot']['id'] for m in client.get('/api/registry').json()}=={'demo_arm','custom_arm'}
        initial={**data['initial_configuration']['actuator_positions'],'base_yaw':.3}
        added=client.post('/api/projects/apple_transfer/robots',json={'id':'custom_01','name':'Custom 01','model_id':'custom_arm','initial_positions':initial,'base_pose':{'x':0,'y':1.5,'z':0,'yaw':0}})
        assert added.status_code==201,added.text
        detail=client.get('/api/projects/apple_transfer').json()
        assert len(detail['robots'])==2
        assert detail['robots'][0]['state']['positions']==original['robots'][0]['state']['positions']
        assert detail['robots'][1]['instance']['robot_model']['id']=='custom_arm'
        assert detail['robots'][1]['state']['positions']==initial
        assert client.get('/api/registry/custom_arm/bundle').json()==data
    with TestClient(create_app(store)) as client:
        assert client.get('/api/projects/apple_transfer').json()['robots'][1]['model']['robot']['name']=='Custom educational arm'


def test_invalid_import_is_atomic_and_executable_references_rejected(store):
    with TestClient(create_app(store)) as client:
        data=bundle(client)
        invalid=copy.deepcopy(data);invalid['actuators']['actuators']['shoulder']['max']=-100
        assert client.post('/api/registry/import',json=invalid).status_code==422
        assert not (store.runtime/'imported_models/custom_arm').exists()
        assert not list((store.runtime/'imported_models').glob('.import-*'))
        invalid=copy.deepcopy(data);invalid['robot']['implementation']='evil.py'
        assert client.post('/api/registry/import',json=invalid).status_code==422
        invalid=copy.deepcopy(data);invalid['robot']['id']='../escape'
        assert client.post('/api/registry/import',json=invalid).status_code==422
        assert client.post('/api/registry/import',json=data).status_code==201
        assert client.post('/api/registry/import',json=data).status_code==422
        assert client.get('/api/registry/demo_arm/bundle').json()['robot']['id']=='demo_arm'


def test_configuration_only_model_is_visible_but_motion_compile_explains_missing_solver(store):
    with TestClient(create_app(store)) as client:
        data=bundle(client,'unverified_arm');data['kinematics']['solver']='custom_untested_v1'
        imported=client.post('/api/registry/import',json=data).json()
        assert imported['planning_supported'] is False
        assert client.post('/api/projects/apple_transfer/robots',json={'id':'custom_01','name':'Unverified','model_id':'unverified_arm','base_pose':{'x':0,'y':2,'z':0,'yaw':0}}).status_code==201
        detail=client.get('/api/projects/apple_transfer').json()
        assert detail['robots'][1]['model']['planning_supported'] is False
        definition=client.post('/api/projects/apple_transfer/plan-definitions',json={'name':'Check unsupported model'}).json()
        path=f"/api/projects/apple_transfer/plan-definitions/{definition['id']}"
        assert client.put(path,json={'name':'Check unsupported model','goal':'','version':1,'tasks':[{'id':'home','name':'Home','operation':'move','robot_id':'custom_01'}]}).status_code==200
        result=client.post(path+'/compile')
        assert result.status_code==422 and 'no verified planner' in result.text


def test_model_selection_and_initial_limits_are_enforced(store):
    with TestClient(create_app(store)) as client:
        data=bundle(client)
        initial=data['initial_configuration']['actuator_positions'].copy();initial['shoulder']=999
        request={'id':'invalid','name':'Invalid','model_id':'demo_arm','initial_positions':initial,'base_pose':{'x':0,'y':2,'z':0,'yaw':0}}
        assert client.post('/api/projects/apple_transfer/robots',json=request).status_code==422
        assert len(client.get('/api/projects/apple_transfer').json()['robots'])==1
        request.update(initial_positions=data['initial_configuration']['actuator_positions'],model_id='does_not_exist')
        assert client.post('/api/projects/apple_transfer/robots',json=request).status_code==404
