import json
import httpx
from services.api.main import create_app
from integrations.gcp.cloud_apps import links

async def test_user_activity_keeps_cloud_session_awake_but_health_polls_do_not(store,tmp_path,monkeypatch):
    activity=tmp_path/'activity';activity.mkdir()
    monkeypatch.setenv('ROBOT_IDE_DEPLOYMENT','cloud');monkeypatch.setenv('ROBOT_IDE_ACTIVITY_DIR',str(activity))
    app=create_app(store)
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
        assert (await client.get('/api/health')).json()['cloud_session']
        assert not list(activity.glob('*.json'))
        assert (await client.post('/api/session/activity')).status_code==200
        stamp=json.loads((activity/'cloud-user.json').read_text())['last_work']
        await client.get('/api/health')
        assert json.loads((activity/'cloud-user.json').read_text())['last_work']==stamp
        assert (await client.post('/api/business/session/activity')).status_code==200
        assert json.loads((activity/'cloud-user.json').read_text())['last_work']>=stamp


def test_public_cloud_links_reject_untrusted_schemes_and_credentials(tmp_path,monkeypatch):
    path=tmp_path/'links.json';monkeypatch.setenv('ROBOT_IDE_CLOUD_LINKS',str(path))
    path.write_text(json.dumps({'ide':'https://workspace-example.trycloudflare.com','business':'javascript:alert(1)','token':'private'}))
    assert links()=={'ide':'https://workspace-example.trycloudflare.com'}
    path.write_text('{not json');assert links()=={}
