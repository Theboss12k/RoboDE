"""NVIDIA/Nebius edition: separate settings, connect-only Nebius tunnel and first-boot setup."""
import json
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.api.isaac import IsaacConfiguration, worker_configuration
from integrations.nebius.tunnel import NebiusTunnel


@pytest.fixture
def nvidia(monkeypatch):
    monkeypatch.setenv('ROBOT_IDE_EDITION','nvidia')
    for key in ('ISAAC_WORKER_URL','ISAAC_WORKER_TOKEN','AI_BASE_URL','AI_MODEL','AI_API_KEY'):monkeypatch.delenv(key,raising=False)


def test_editions_keep_separate_isaac_connections(store,monkeypatch,nvidia):
    gcp={'deployment':'gcp','gcp_project':'p','gcp_zone':'z','gcp_instance':'vm','token':'x'*20}
    (store.runtime/'connections').mkdir(parents=True,exist_ok=True)
    (store.runtime/'connections/isaac.json').write_text(json.dumps(gcp))
    assert worker_configuration(store)['deployment']=='nebius'
    monkeypatch.setenv('ROBOT_IDE_EDITION','standard')
    assert worker_configuration(store)['gcp_instance']=='vm'


def test_nebius_configuration_requires_host_and_loopback_tunnel():
    with pytest.raises(ValueError,match='Nebius VM public IP'):
        IsaacConfiguration(deployment='nebius',token='x'*20)
    with pytest.raises(ValueError,match='SSH tunnel'):
        IsaacConfiguration(deployment='nebius',nebius_host='203.0.113.5',url='https://203.0.113.5',token='x'*20)
    for host in ('-oProxyCommand=sh','a b','host;rm'):
        with pytest.raises(ValueError):
            IsaacConfiguration(deployment='nebius',nebius_host=host,token='x'*20)
    with pytest.raises(ValueError):
        IsaacConfiguration(deployment='nebius',nebius_host='203.0.113.5',nebius_ssh_user='-oProxy',token='x'*20)


def test_nebius_tunnel_forwards_worker_ports_without_shell(tmp_path):
    key=tmp_path/'id_ed25519';key.write_text('test')
    c=IsaacConfiguration(deployment='nebius',nebius_host='203.0.113.5',nebius_ssh_user='ubuntu',ssh_key_file=str(key),token='x'*20).model_dump()
    args=NebiusTunnel.command(c)
    assert args[0]=='ssh' and args[-1]=='ubuntu@203.0.113.5'
    assert ['-L','9100:127.0.0.1:9100'] == args[2:4] and '-N' in args and ['-i',str(key)] == args[args.index('-i'):args.index('-i')+2]
    with pytest.raises(ValueError,match='SSH key file is missing'):
        NebiusTunnel.command({**c,'ssh_key_file':str(tmp_path/'missing')})


def test_first_boot_setup_saves_nebius_isaac_and_token_factory_default(store,nvidia):
    standard=(store.runtime/'connections/isaac.json').read_text()
    with TestClient(create_app(store)) as client:
        first=client.get('/api/setup').json()
        assert first['edition']=='nvidia' and not first['completed'] and first['defaults']['compute']=='nebius'
        assert client.get('/api/health').json()['edition']=='nvidia'
        missing=client.put('/api/setup',json={'simulator':'isaac_sim','compute':'nebius','nebius_host':'','ai':'skip'})
        assert missing.status_code==422 and not client.get('/api/setup').json()['completed']
        no_key=client.put('/api/setup',json={'simulator':'isaac_sim','compute':'nebius','nebius_host':'203.0.113.5','ai':'token_factory','ai_model':'nvidia/nemotron-test'})
        assert no_key.status_code==422 and 'API key' in no_key.text
        assert not (store.runtime/'connections/isaac.nvidia.json').exists()
        done=client.put('/api/setup',json={'simulator':'isaac_sim','compute':'nebius','nebius_host':'203.0.113.5','ai':'token_factory',
                                           'ai_model':'nvidia/nemotron-test','ai_api_key':'private-test-key'}).json()
        assert done['completed'] and 'ai_api_key' not in json.dumps(done)
        isaac=client.get('/api/configuration/isaac').json()
        assert (isaac['deployment'],isaac['nebius_host'],isaac['url'],isaac['has_token'])==('nebius','203.0.113.5','http://127.0.0.1:9100',True)
        assert (store.runtime/'connections/isaac.json').read_text()==standard
        models=client.get('/api/llm/adapters').json()
        default=next(a for a in models['adapters'] if a['id']==models['default_id'])
        assert (default['model'],default['base_url'],default['has_api_key'])==('nvidia/nemotron-test','https://api.tokenfactory.nebius.com/v1',True)
        assert 'private-test-key' not in (store.runtime/'setup/nvidia.json').read_text()
        project=client.post('/api/projects',json={'name':'NVIDIA demo'}).json()
        assert project['simulation']['adapter']=='isaac_sim'
        status=client.get('/api/configuration/isaac/nebius').json()
        assert status['configured'] and status['status']=='disconnected'


def test_standard_edition_keeps_source_simulator_until_setup(store,monkeypatch):
    monkeypatch.delenv('ROBOT_IDE_EDITION',raising=False)
    with TestClient(create_app(store)) as client:
        assert client.get('/api/setup').json()['edition']=='standard'
        project=client.post('/api/projects',json={'name':'Standard'}).json()
        assert project['simulation']['adapter']=='mock'


@pytest.mark.parametrize('name',['standard','nvidia'])
def test_sign_in_page_uses_edition_accent(monkeypatch,name):
    from web.gateway import create_gateway
    monkeypatch.setenv('ROBOT_IDE_EDITION',name)
    with TestClient(create_gateway(code='test-access-12345',scope='ide')) as client:
        page=client.get('/login').text
    assert ('#76b900' in page)==(name=='nvidia') and ('#90baff' in page)==(name=='standard')
    assert ('RoboDE for NVIDIA' in page)==(name=='nvidia') and 'Configuration → Workspace.' in page
    with TestClient(create_gateway(code='test-access-12345',scope='business')) as client:
        assert '#76b900' not in client.get('/business/login').text


def test_first_boot_setup_can_choose_separate_planner_and_task_llms(store,nvidia):
    with TestClient(create_app(store)) as client:
        done=client.put('/api/setup',json={'simulator':'builtin','ai':'token_factory','ai_model':'nvidia/planner-model',
                                           'ai_task_model':'nvidia/task-model','ai_api_key':'private-test-key'})
        assert done.status_code==200,done.text
        models={a['id']:a for a in client.get('/api/llm/adapters').json()['adapters']}
        roles=client.get('/api/llm/roles').json()
        assert models[roles['planner_adapter_id']]['model']=='nvidia/planner-model'
        assert models[roles['binding_adapter_id']]['model']=='nvidia/task-model' and models[roles['binding_adapter_id']]['has_api_key']
