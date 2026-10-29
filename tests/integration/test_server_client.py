"""The browser gateway authenticates; the real shared runtime compiles and runs plans."""
import httpx
import pytest
from services.api.main import create_app
from web.gateway import create_gateway


async def test_authenticated_remote_browser_uses_shared_server_engine(store,tmp_path):
    dist=tmp_path/'client';dist.mkdir();(dist/'index.html').write_text('<div id="root">React IDE</div>');(dist/'editor.worker.js').write_text('/* locally served worker */')
    runtime=create_app(store,speed=1000)
    gateway=create_gateway(dist=dist,code='shared-team-access-123',scope='ide',transport=httpx.ASGITransport(app=runtime))
    transport=httpx.ASGITransport(app=gateway)
    async with runtime.router.lifespan_context(runtime),gateway.router.lifespan_context(gateway):
        async with httpx.AsyncClient(transport=transport,base_url='https://robot-server.example') as alice,httpx.AsyncClient(transport=transport,base_url='https://robot-server.example') as bob:
            assert (await alice.get('/')).status_code==303
            assert (await alice.get('/editor.worker.js')).status_code==303
            assert (await alice.get('/api/projects')).status_code==401
            login=await alice.post('/login',content='code=shared-team-access-123')
            assert login.status_code==303 and login.headers['location']=='/'
            assert 'Secure' in login.headers['set-cookie'] and 'HttpOnly' in login.headers['set-cookie']
            assert 'React IDE' in (await alice.get('/')).text
            assert (await alice.get('/editor.worker.js')).status_code==200
            assert (await bob.get('/api/projects')).status_code==401
            assert (await bob.post('/login',content='code=shared-team-access-123')).status_code==303
            project=(await alice.post('/api/projects',json={'name':'Shared server project','source':'apple_transfer'})).json()
            pid=project['id']
            # Another browser sees the same project on the server.
            assert pid in {p['id'] for p in (await bob.get('/api/projects')).json()}
            definition=(await alice.post(f'/api/projects/{pid}/plan-definitions',json={'name':'Move a joint','goal':'Turn the robot'})).json()
            task={'id':'turn','name':'Turn','operation':'command','robot_id':'arm_01','dependencies':[],
                  'command':{'type':'SET_ACTUATOR','target':'base_yaw','value':.1,'unit':'rad'}}
            result=await alice.put(f'/api/projects/{pid}/plan-definitions/'+definition['id'],json={'version':definition['version'],'name':definition['name'],'goal':definition['goal'],'tasks':[task]})
            assert result.status_code==200,result.text
            compiled=await alice.post(f'/api/projects/{pid}/plan-definitions/'+definition['id']+'/compile')
            assert compiled.status_code==201,compiled.text
            revision=compiled.json();assert revision['valid'] and revision['code']
            # Artifacts were calculated and saved by the server, not the browser.
            saved=store.get_plan(pid,revision['id']);assert saved.fingerprint==revision['fingerprint']
            assert saved.atomic_tasks[0].robot_id=='arm_01'
            rejected=await bob.post('/api/projects',json={'name':'Forged origin'},headers={'Origin':'https://untrusted.example'})
            assert rejected.status_code==403
            assert (await alice.post('/logout')).status_code==303
            assert (await alice.get('/api/projects')).status_code==401
            assert (await bob.get('/api/projects')).status_code==200


async def test_private_runtime_rejects_direct_remote_hosts(store):
    runtime=create_app(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime),base_url='http://public-server.example') as client:
        assert (await client.get('/api/projects')).status_code==403


def test_ide_gateway_requires_built_react_client(tmp_path):
    with pytest.raises(ValueError,match='Build the React IDE'):
        create_gateway(dist=tmp_path/'missing',code='shared-team-access-123',scope='ide')


async def test_workspace_access_code_requires_ide_session_and_is_never_cached(tmp_path):
    dist=tmp_path/'client';dist.mkdir();(dist/'index.html').write_text('IDE')
    expected='workspace-reveal-test-code'
    gateway=create_gateway(dist=dist,code=expected,scope='ide')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway),base_url='https://workspace.example') as client:
        assert expected not in (await client.get('/login')).text
        assert (await client.post('/api/workspace/access')).status_code==401
        await client.post('/login',content='code='+expected)
        response=await client.post('/api/workspace/access')
        assert response.status_code==200 and response.json()=={'access_code':expected}
        assert response.headers['cache-control']=='no-store' and response.headers['pragma']=='no-cache'
        assert (await client.post('/api/workspace/access',headers={'Origin':'https://untrusted.example'})).status_code==403
        await client.post('/logout')
        assert (await client.post('/api/workspace/access')).status_code==401
    business=create_gateway(dist=dist,code='different-business-code',scope='business')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=business),base_url='https://business.example') as client:
        await client.post('/login',content='code=different-business-code')
        response=await client.post('/api/workspace/access')
        assert response.status_code==404 and expected not in response.text

async def test_project_clone_and_run_history_with_external_persistent_projects(store,tmp_path):
    """Cloud deployments mount writable projects separately from read-only code."""
    external=tmp_path/'persistent-projects'
    store.projects.rename(external)
    store.projects.symlink_to(external,target_is_directory=True)
    runtime=create_app(store,speed=1000)
    async with runtime.router.lifespan_context(runtime),httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime),base_url='http://testserver') as client:
        response=await client.post('/api/projects',json={'name':'Mounted workspace','source':'apple_transfer'})
        assert response.status_code==201,response.text
        pid=response.json()['id']
        base=f'/api/projects/{pid}/plan-definitions'
        definition=(await client.post(base,json={'name':'Turn','goal':'Turn the robot'})).json()
        task={'id':'turn','name':'Turn','operation':'command','robot_id':'arm_01','dependencies':[], 'command':{'type':'SET_ACTUATOR','target':'base_yaw','value':.1,'unit':'rad'}}
        saved=await client.put(base+'/'+definition['id'],json={'version':definition['version'],'name':'Turn','goal':'Turn the robot','tasks':[task]})
        assert saved.status_code==200,saved.text
        compiled=await client.post(base+'/'+definition['id']+'/compile');assert compiled.status_code==201,compiled.text
        revision=compiled.json();assert revision['valid']
        started=await client.post(f'/api/projects/{pid}/plans/'+revision['id']+'/simulate',json={'fingerprint':revision['fingerprint'],'adapter':'mock','mode':'simulation'})
        assert started.status_code==202,started.text
        import asyncio
        for _ in range(100):
            run=(await client.get('/api/runs/'+started.json()['id'])).json()
            if run.get('finished_at'):break
            await asyncio.sleep(.02)
        assert run['status']=='SIMULATION_PASSED'
        assert store.get_run(run['id']).project_id==pid
