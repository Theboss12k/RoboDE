from fastapi.testclient import TestClient
from BUSINESS_APP.server import create_gateway


def test_gateway_requires_login_and_limits_api_surface(tmp_path):
    (tmp_path/'index.html').write_text('<h1>Business app</h1>')
    with TestClient(create_gateway(dist=tmp_path,code='test-access-12345'),follow_redirects=False) as client:
        assert client.get('/business/').status_code==303
        assert client.get('/api/business/projects').status_code==401
        assert client.post('/login',content='code=wrong').status_code==401
        login=client.post('/login',content='code=test-access-12345')
        assert login.status_code==303 and 'HttpOnly' in login.headers['set-cookie']
        assert client.get('/business/').status_code==200
        assert client.get('/api/configuration/llm').status_code==404
        assert client.post('/api/business/gpu/start',headers={'Origin':'https://evil.example'}).status_code==403
        assert client.post('/logout').status_code==303
        assert client.get('/api/business/projects').status_code==401


def test_unprotected_gateway_refuses_public_host_and_rate_limits_passwords():
    with TestClient(create_gateway()) as client:assert client.get('/',headers={'Host':'example.com'}).status_code==403
    with TestClient(create_gateway(code='test-access-12345')) as client:
        for _ in range(10):assert client.post('/login',content='code=wrong').status_code==401
        assert client.post('/login',content='code=wrong').status_code==429


def test_install_metadata_public_without_exposing_workspace(tmp_path):
    for name in ['manifest.webmanifest','app-icon-192.png','app-icon-512.png']:(tmp_path/name).write_text('{}')
    (tmp_path/'index.html').write_text('private workspace')
    with TestClient(create_gateway(dist=tmp_path,code='test-access-12345'),follow_redirects=False) as client:
        for name in ['manifest.webmanifest','app-icon-192.png','app-icon-512.png']:assert client.get('/business/'+name).status_code==200
        assert client.get('/business/').status_code==303
        assert client.get('/api/business/projects').status_code==401
        assert client.get('/business/room-capture.html').status_code==303


def test_business_pwa_login_stays_in_installation_scope(tmp_path):
    (tmp_path/'index.html').write_text('workspace')
    with TestClient(create_gateway(dist=tmp_path,code='test-access-12345'),follow_redirects=False) as client:
        assert client.get('/business/').headers['location']=='/business/login'
        page=client.get('/business/login')
        assert page.status_code==200 and 'action="/business/login"' in page.text
        assert client.post('/business/login',content='code=test-access-12345').headers['location']=='/business/'
        assert client.get('/business/').status_code==200
        assert client.post('/logout').headers['location']=='/business/login'
        assert client.get('/api/business/projects').status_code==401
