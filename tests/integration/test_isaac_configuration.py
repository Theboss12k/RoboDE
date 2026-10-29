import json
import os
from fastapi.testclient import TestClient
from services.api.main import create_app


def test_worker_configuration_redacts_secrets_and_uses_private_storage(store):
    app=create_app(store)
    with TestClient(app) as client:
        result=client.put('/api/configuration/isaac',json={'url':'http://127.0.0.1:9100','token':'a-private-worker-token','load_scene':True,'gcp_project':'my-project','gcp_zone':'zone','gcp_instance':'vm'})
        assert result.status_code==200,result.text
        assert 'token' not in result.json() and result.json()['has_token']
        assert 'a-private-worker-token' not in client.get('/api/configuration/isaac').text
        path=store.runtime/'connections/isaac.json'
        assert path.stat().st_mode&0o777==0o600
        assert client.put('/api/configuration/isaac',json={'url':'http://127.0.0.1:9101','token':None}).status_code==200
        assert json.loads(path.read_text())['token']=='a-private-worker-token'
        for url in ['http://remote.test:9100','file:///tmp/a','https://secret@worker.test','https://worker.test/path']:
            assert client.put('/api/configuration/isaac',json={'url':url,'token':'a-private-worker-token'}).status_code==422
        app.state.controller.resources.acquire(['device:test'],'owner')
        assert client.put('/api/configuration/isaac',json={'url':'http://localhost:9100'}).status_code==422
        app.state.controller.resources.release('owner')


def test_deployment_defaults_legacy_compatibility_and_local_cloud_isolation(store,monkeypatch):
    from services.api.isaac import worker_configuration
    from services.api.storage import atomic_json
    (store.runtime/'connections/isaac.json').unlink()
    monkeypatch.delenv('ISAAC_WORKER_URL',raising=False);monkeypatch.delenv('ISAAC_WORKER_TOKEN',raising=False)
    monkeypatch.setattr('services.api.isaac.sys',type('Host',(),{'platform':'darwin'}))
    assert worker_configuration(store)['deployment']=='gcp'
    atomic_json(store.runtime/'connections/isaac.json',{'url':'http://127.0.0.1:9101','token':'legacy-private-token'})
    assert worker_configuration(store)['deployment']=='remote'
    app=create_app(store)
    with TestClient(app) as client:
        capabilities=client.get('/api/configuration/isaac/setup')
        assert capabilities.status_code==200
        draft=client.post('/api/configuration/isaac/token').json()['token']
        assert len(draft)>=32
        assert json.loads((store.runtime/'connections/isaac.json').read_text())['token']=='legacy-private-token'
        result=client.put('/api/configuration/isaac',json={'deployment':'local','token':draft,'url':'http://127.0.0.1:9100',
            'local_launcher':'/opt/isaacsim/python.sh','local_source':'/data/catalog.yaml','load_scene':True})
        assert result.status_code==200,result.text
        assert 'token' not in result.json() and result.json()['deployment']=='local'
        assert client.put('/api/configuration/isaac',json={'deployment':'local','token':draft,'on_demand':True,
            'gcp_project':'p','gcp_zone':'z','gcp_instance':'vm'}).status_code==422
        assert client.put('/api/configuration/isaac',json={'deployment':'local','url':'https://worker.example','token':draft}).status_code==422
        app.state.controller.resources.acquire(['robot:test'],'a-plan')
        assert client.post('/api/configuration/isaac/local/start').status_code==422
        assert client.post('/api/configuration/isaac/local/stop').status_code==422
        app.state.controller.resources.release('a-plan')
        monkeypatch.setattr('integrations.local_isaac.host_capabilities',lambda:{'local_supported':False})
        assert 'macOS' in client.post('/api/configuration/isaac/local/start').json()['detail']
        assert app.state.controller.local_isaac.process is None


def test_ssh_key_path_validation_and_persistence(store,tmp_path):
    with TestClient(create_app(store)) as client:
        settings={'deployment':'gcp','ssh_key_file':str(tmp_path/'IDE key'),'token':'test-private-worker-token'}
        response=client.put('/api/configuration/isaac',json=settings)
        assert response.status_code==200,response.text
        assert client.get('/api/configuration/isaac').json()['ssh_key_file']==settings['ssh_key_file']
        for invalid in ['relative/key','/absolute/key\nother','/absolute/key\0other']:
            assert client.put('/api/configuration/isaac',json={**settings,'ssh_key_file':invalid}).status_code==422
