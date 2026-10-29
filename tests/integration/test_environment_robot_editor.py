"""Draft robot controls use isolated transports; starting points commit explicitly."""
import copy
import math
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app


def payload(detail,**changes):
    robot=detail['robots'][0]
    return {'base_pose':robot['instance'].get('base_pose',dict(x=0.,y=0.,z=0.,yaw=0.)),
        'positions':robot['state']['positions'],'expected_instance':robot['instance'],
        'expected_positions':robot['state']['positions'],**changes}


def test_draft_transport_uses_mapping_and_draft_base_without_mutating_world(store):
    with TestClient(create_app(store)) as client:
        before=client.get('/api/projects/apple_transfer').json()
        body={'model_id':'demo_arm','name':'Physical preview','kind':'sdk','configuration_method':'custom',
            'joint_mapping':{k:'remote_'+k for k in before['state']['positions']},
            'remote_units':{k:('deg' if k!='gripper' else 'mm') for k in before['state']['positions']},
            'connection':{'bridge_url':'http://127.0.0.1:1','token_env':'NO_HARDWARE_TOKEN'}}
        adapter=client.post('/api/projects/apple_transfer/adapters/generate',json=body).json()
        client.post('/api/adapters/'+adapter['id']+'/review',json={'expected_hash':adapter['hash']})
        assert client.post('/api/adapters/'+adapter['id']+'/test').json()['test_report']['passed']
        q={**before['state']['positions'],'base_yaw':.12}
        preview={'positions':q,'base_pose':dict(x=.7,y=.1,z=0.,yaw=.3)}
        opened=client.post('/api/projects/apple_transfer/controls',json={'robot_id':'arm_01','adapter_id':adapter['id'],'preview':preview})
        assert opened.status_code==201,opened.text
        s=opened.json();url='/api/controls/'+s['id']
        assert s['feedback']['source']=='simulation' and not s['armed']
        assert s['feedback']['positions']==pytest.approx(q)
        assert s['feedback']['translated_command']['remote_base_yaw']==pytest.approx(math.degrees(.12))
        pose=client.get(url+'/tool-poses').json()['positions']['parallel_gripper']
        response=client.post(url+'/standard-command',json={'type':'MOVE_END_EFFECTOR','target':'parallel_gripper','position':pose,'position_unit':'m','frame':'world'})
        assert response.status_code==200,response.text
        assert client.put(url+'/preview-base',json=dict(x=.8,y=.1,z=0.,yaw=.3)).status_code==200
        moved_pose=client.get(url+'/tool-poses').json()['positions']['parallel_gripper']
        assert moved_pose[0]-pose[0]==pytest.approx(.1)
        assert client.post(url+'/standard-command',json={'type':'SET_ACTUATOR','target':'elbow','value':999.,'unit':'rad'}).status_code==422
        after=client.get('/api/projects/apple_transfer').json()
        assert after['instance']==before['instance'] and after['state']['positions']==before['state']['positions']
        assert after['fingerprint']==before['fingerprint']
        stopped=client.post(url+'/stop').json()
        assert stopped['stop_requested'] and stopped['stopped_verified']
        assert client.delete(url).status_code==200
        assert client.post('/api/projects/apple_transfer/controls',json={'robot_id':'arm_01','adapter_id':adapter['id'],'mode':'live','preview':preview}).status_code==422


def test_apply_starting_point_saves_base_and_joints_updates_preview_and_rejects_stale(store):
    path=store.project_folder('apple_transfer')/'robots/arm_01/instance.yaml'
    with TestClient(create_app(store)) as client:
        before=client.get('/api/projects/apple_transfer').json()
        q={**before['state']['positions'],'base_yaw':.05}
        data=payload(before,positions=q,base_pose=dict(x=.05,y=.0,z=0.,yaw=.1))
        response=client.put('/api/projects/apple_transfer/robots/arm_01/starting-state',json=data)
        assert response.status_code==200,response.text
        after=client.get('/api/projects/apple_transfer').json()
        assert after['instance']['base_pose']==data['base_pose']
        assert after['instance']['initial_configuration']['actuator_positions']==q
        assert after['state']['positions']==q
        assert after['fingerprint']!=before['fingerprint']
        saved=path.read_text()
        assert client.put('/api/projects/apple_transfer/robots/arm_01/starting-state',json=data).status_code==422
        assert path.read_text()==saved
        assert client.post('/api/projects/apple_transfer/reset').status_code==200
        assert client.get('/api/projects/apple_transfer').json()['state']['positions']==q


def test_invalid_starting_point_and_active_controls_never_commit(store):
    path=store.project_folder('apple_transfer')/'robots/arm_01/instance.yaml'
    with TestClient(create_app(store)) as client:
        before=client.get('/api/projects/apple_transfer').json();saved=path.read_text()
        invalid=payload(before,positions={**before['state']['positions'],'elbow':999.})
        assert client.put('/api/projects/apple_transfer/robots/arm_01/starting-state',json=invalid).status_code==422
        # Static endpoint validation includes the ground, obstacles and other robots.
        invalid=payload(before,base_pose=dict(x=0.,y=0.,z=-1.,yaw=0.))
        assert client.put('/api/projects/apple_transfer/robots/arm_01/starting-state',json=invalid).status_code==422
        stale=payload(before,expected_positions={**before['state']['positions'],'base_yaw':.1})
        assert client.put('/api/projects/apple_transfer/robots/arm_01/starting-state',json=stale).status_code==422
        opened=client.post('/api/projects/apple_transfer/controls',json={'robot_id':'arm_01','adapter_id':'mock','mode':'environment'}).json()
        assert client.put('/api/projects/apple_transfer/robots/arm_01/starting-state',json=payload(before)).status_code==422
        assert client.put('/api/controls/'+opened['id']+'/preview-base',json=dict(x=0.,y=0.,z=0.,yaw=0.)).status_code==422
        client.delete('/api/controls/'+opened['id'])
        assert path.read_text()==saved
        assert client.get('/api/projects/apple_transfer').json()['state']['positions']==before['state']['positions']


def test_starting_point_rolls_back_if_state_persistence_fails(store,monkeypatch):
    app=create_app(store)
    path=store.project_folder('apple_transfer')/'robots/arm_01/instance.yaml'
    async def fail(*args):raise OSError('Simulated state disk failure')
    with TestClient(app,raise_server_exceptions=False) as client:
        before=client.get('/api/projects/apple_transfer').json();saved=path.read_text()
        monkeypatch.setattr(app.state.controller,'persist_state',fail)
        data=payload(before,positions={**before['state']['positions'],'base_yaw':.1},base_pose=dict(x=.05,y=0.,z=0.,yaw=.1))
        assert client.put('/api/projects/apple_transfer/robots/arm_01/starting-state',json=data).status_code==500
        assert path.read_text()==saved
        after=client.get('/api/projects/apple_transfer').json()
        assert after['state']['positions']==before['state']['positions']
        assert after['instance']==before['instance']
        assert not app.state.controller.resources.owners


def test_starting_point_preserves_other_robots_and_rejects_overlapping_bases(store):
    import yaml
    folder=store.project_folder('apple_transfer')
    project=yaml.safe_load((folder/'project.yaml').read_text())
    first=yaml.safe_load((folder/project['robots'][0]).read_text())
    second=copy.deepcopy(first);second['instance']['id']='arm_02';second['instance']['name']='Second arm'
    second['base_pose']=dict(x=0.,y=1.3,z=0.,yaw=0.)
    path=folder/'robots/arm_02/instance.yaml';path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(second))
    project['robots'].append('robots/arm_02/instance.yaml')
    (folder/'project.yaml').write_text(yaml.safe_dump(project))
    with TestClient(create_app(store)) as client:
        before=client.get('/api/projects/apple_transfer').json()
        data=payload(before,positions={**before['state']['positions'],'base_yaw':.05},base_pose=dict(x=.05,y=0.,z=0.,yaw=.1))
        response=client.put('/api/projects/apple_transfer/robots/arm_01/starting-state',json=data)
        assert response.status_code==200,response.text
        after=client.get('/api/projects/apple_transfer').json()
        assert after['robots'][1]['instance']==before['robots'][1]['instance']
        assert after['robots'][1]['state']['positions']==before['robots'][1]['state']['positions']
        overlap=payload(after,base_pose=second['base_pose'])
        response=client.put('/api/projects/apple_transfer/robots/arm_01/starting-state',json=overlap)
        assert response.status_code==422 and 'Inter-robot proximity' in response.text
        assert client.get('/api/projects/apple_transfer').json()['instance']==after['instance']
