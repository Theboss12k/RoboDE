import copy
import httpx
from services.api.main import create_app

async def test_global_robot_adapter_setup_without_project_and_persistent_instance_binding(store):
    app=create_app(store)
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
        original=(await c.get('/api/projects')).json()
        bundle=(await c.get('/api/registry/demo_arm/bundle')).json();bundle['robot'].update(id='global_test',name='Global Test')
        assert (await c.post('/api/registry/import',json=bundle)).status_code==201
        preview=(await c.get('/api/library/robots/global_test/preview')).json()
        assert preview['project']['id']=='library:global_test'
        generated=(await c.post('/api/library/robots/global_test/adapters/generate',json={'model_id':'global_test','kind':'sdk','target':'physical','configuration_method':'custom','name':'Custom SDK'})).json()
        aid=generated['id']
        assert (await c.post(f'/api/adapters/{aid}/review',json={'expected_hash':generated['hash']})).status_code==200
        tested=(await c.post(f'/api/adapters/{aid}/test')).json();assert tested['test_report']['passed']
        opened=(await c.post('/api/library/robots/global_test/controls',json={'adapter_id':aid,'category':'physical'})).json();sid=opened['id']
        assert opened['mode']=='test' and opened['feedback']['source']=='simulation'
        command={'type':'SET_ACTUATOR','target':'base_yaw','value':.1,'unit':'rad'}
        assert (await c.post(f'/api/controls/{sid}/standard-command',json=command)).status_code==200
        assert (await c.post('/api/library/robots/global_test/controls',json={'adapter_id':aid,'category':'physical','mode':'live'})).status_code==422
        assert (await c.delete(f'/api/controls/{sid}')).status_code==200
        assert (await c.get('/api/projects')).json()==original
        assert not list(store.projects.glob('library*'))
        add=await c.post('/api/projects/apple_transfer/robots',json={'id':'new_robot','name':'New robot','model_id':'global_test','adapter_id':aid,'category':'physical','initial_positions':{**generated['initial'],'base_yaw':.25},'base_pose':{'x':0.,'y':2.,'z':0.,'yaw':0.}})
        assert add.status_code==201,add.text
        assert store.load_project('apple_transfer')[1][-1]['control_adapter']['adapter_id']==aid
        session=(await c.post('/api/projects/apple_transfer/controls',json={'robot_id':'new_robot','adapter_id':aid,'mode':'test'})).json()
        assert session['feedback']['positions']['base_yaw']==.25
        await c.delete('/api/controls/'+session['id'])
        assert (await c.put('/api/projects/apple_transfer/robots/new_robot/adapter',json={'adapter_id':'mock','category':'physical'})).status_code==422
        saved=await c.put('/api/projects/apple_transfer/robots/new_robot/adapter',json={'adapter_id':'mock','category':'virtual'});assert saved.status_code==200,saved.text
        assert store.load_project('apple_transfer')[1][-1]['control_adapter']['adapter_id']=='mock'
        bad=await c.post('/api/library/robots/demo_arm/controls',json={'adapter_id':aid,'category':'physical'});assert bad.status_code==422

async def test_draft_or_wrong_robot_adapter_cannot_be_assigned(store):
    app=create_app(store)
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
        generated=(await c.post('/api/library/robots/demo_arm/adapters/generate',json={'model_id':'demo_arm','kind':'mock','name':'Unreviewed'})).json()
        r=await c.put('/api/projects/apple_transfer/robots/arm_01/adapter',json={'adapter_id':generated['id'],'category':'virtual'})
        assert r.status_code==422 and 'Review' in r.text

async def test_global_model_edit_uses_data_copy_without_duplicate_registry_entries(store):
    from services.validation.registry import MODEL_ROOT
    before=(MODEL_ROOT/'demo_arm/actuators.yaml').read_bytes()
    app=create_app(store)
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
        model=next(m for m in (await c.get('/api/registry')).json() if m['robot']['id']=='demo_arm')
        model['actuators']['actuators']['base_yaw']['velocity']=1.4
        response=await c.put('/api/registry/demo_arm/configuration',json={'actuators':model['actuators']['actuators'],'capabilities':model['capabilities']});assert response.status_code==200,response.text
        rows=[m for m in (await c.get('/api/registry')).json() if m['robot']['id']=='demo_arm']
        assert len(rows)==1 and rows[0]['actuators']['actuators']['base_yaw']['velocity']==1.4
        assert (MODEL_ROOT/'demo_arm/actuators.yaml').read_bytes()==before

async def test_global_limits_keep_the_robot_template_valid(store):
    app=create_app(store)
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
        model=next(m for m in (await c.get('/api/registry')).json() if m['robot']['id']=='demo_arm')
        # Even without project instances, the factory initial state must remain usable.
        model['actuators']['actuators']['gripper']['max']=.04
        response=await c.put('/api/registry/demo_arm/configuration',json={'actuators':model['actuators']['actuators'],'capabilities':model['capabilities']})
        assert response.status_code==422
        assert (await c.get('/api/registry')).status_code==200
