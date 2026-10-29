import copy
import math
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.planning.kinematics import with_base
from services.planning.workspace import reachable_workspace


def test_workspace_samples_have_physical_bounds_and_include_straight_reach(model):
    result = reachable_workspace(model)
    assert result['available'] and result['sample_count'] > 1000
    assert result['units']=='m' and result['frame']=='world'
    assert result['bounds']['max'][0] == .6
    assert (.6,0.,.16) in result['points']
    for x,y,z in result['points']:
        assert z>=.022-1e-6
        assert math.dist((x,y,z),(0,0,.16))<=.600002
    assert 'orientation' in result['scope'] and 'Obstacles' in result['scope']


def test_workspace_obeys_saved_joint_limits_and_base_transform(model,instance):
    constrained=copy.deepcopy(model)
    for key,(low,high) in {'base_yaw':(.3,.4),'shoulder':(.8,1.),'elbow':(-1.,-.8)}.items():
        constrained['actuators']['actuators'][key].update(min=low,max=high)
    first=reachable_workspace(constrained)
    assert first['available']
    for x,y,z in first['points']:
        assert .3-1e-5 <= math.atan2(y,x) <= .4+1e-5
        radius=math.hypot(x,y);height=z-.16
        cosine=(radius*radius+height*height-.32**2-.28**2)/(2*.32*.28)
        elbow=-math.acos(max(-1,min(1,cosine)))
        shoulder=math.atan2(height,radius)-math.atan2(.28*math.sin(elbow),.32+.28*math.cos(elbow))
        assert -1.00002<=elbow<=-.8+2e-5
        assert .8-2e-5<=shoulder<=1.+2e-5
    placed=copy.deepcopy(instance);placed['base_pose']={'x':1.,'y':2.,'z':.4,'yaw':math.pi/2}
    second=reachable_workspace(with_base(constrained,placed))
    assert second['available'] and second['sample_count']==first['sample_count']
    for axis in range(3):
        expected=([1-first['bounds']['max'][1],2+first['bounds']['min'][0],.4+first['bounds']['min'][2]][axis])
        assert math.isclose(second['bounds']['min'][axis],expected,abs_tol=2e-6)
    assert second['bounds'] != first['bounds']


def test_workspace_does_not_invent_geometry_for_unsupported_models_or_invalid_table_clearance(model):
    unknown=copy.deepcopy(model);unknown['kinematics']['solver']='unknown_solver'
    result=reachable_workspace(unknown)
    assert result['available'] is False and result['points']==[] and result['bounds'] is None
    assert 'verified' in result['reason']
    low=copy.deepcopy(model);low['kinematics']['links']['base_height']=.001
    result=reachable_workspace(low)
    assert not result['available'] and 'table clearance' in result['reason']


def test_workspace_api_is_read_only_offline_and_respects_project_instance_placement(store,monkeypatch):
    app=create_app(store)
    with TestClient(app) as client:
        before=client.get('/api/projects/apple_transfer').json()
        assert client.post('/api/projects/apple_transfer/disconnect').status_code==200
        async def no_connection(*args,**kwargs):raise AssertionError('Workspace must not connect to or move a simulator')
        monkeypatch.setattr(app.state.controller,'context',no_connection)
        response=client.get('/api/projects/apple_transfer/robots/arm_01/workspace')
        assert response.status_code==200,response.text
        data=response.json()
        assert data['robot_id']=='arm_01' and data['sample_count']>1000
        assert client.get('/api/projects/apple_transfer/robots/missing/workspace').status_code==422
        assert store.load_project('apple_transfer')[1][0]==before['instance']
        assert store.load_project('apple_transfer')[3][0].model_dump()==before['objects'][0]
        assert 'apple_transfer' in app.state.controller.offline
