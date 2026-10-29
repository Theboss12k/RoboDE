import io
import json
from pathlib import Path
import zipfile
from fastapi.testclient import TestClient
from integrations.nurec.service import create_worker

TOKEN='test-nurec-worker-token-123456'
HEADERS={'Authorization':'Bearer '+TOKEN}


def photos(count=12):
    body=io.BytesIO()
    with zipfile.ZipFile(body,'w') as z:
        for i in range(count):z.writestr(f'{i}.jpg',b'\xff\xd8\xffphoto')
    return body.getvalue()


def test_nurec_auth_readiness_and_input_contract(tmp_path,monkeypatch):
    grut=tmp_path/'3dgrut';grut.mkdir();(grut/'train.py').touch()
    monkeypatch.setattr('integrations.nurec.service.shutil.which',lambda name:None)
    with TestClient(create_worker(tmp_path/'jobs',TOKEN,grut)) as client:
        assert client.get('/v1/health').status_code==401
        assert not client.get('/v1/health',headers=HEADERS).json()['ready']
        assert client.post('/v1/jobs',headers=HEADERS,content=photos()).status_code==422
        monkeypatch.setattr('integrations.nurec.service.shutil.which',lambda name:'/test/'+name)
        assert client.post('/v1/jobs',headers=HEADERS,content=photos(11)).status_code==422
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:
            for i in range(12):z.writestr(f'../{i}.jpg',b'image')
        assert client.post('/v1/jobs',headers=HEADERS,content=archive.getvalue()).status_code==422
        assert not list((tmp_path/'jobs').iterdir())


def test_nurec_pipeline_uses_fixed_argv_and_exports_artifact(tmp_path,monkeypatch):
    import time
    grut=tmp_path/'3dgrut';grut.mkdir();(grut/'train.py').touch()
    monkeypatch.setattr('integrations.nurec.service.shutil.which',lambda name:'/test/'+name)
    commands=[]
    class Process:
        returncode=0
        async def wait(self):return 0
    async def launch(*args,**kwargs):
        commands.append(args)
        assert kwargs['start_new_session'] and 'shell' not in kwargs
        out=next((a.removeprefix('out_dir=') for a in args if a.startswith('out_dir=')),None)
        if out:
            path=Path(out)/'room';path.mkdir(parents=True)
            with zipfile.ZipFile(path/'export_last.usdz','w') as z:z.writestr('room.usda','#usda 1.0')
        return Process()
    monkeypatch.setattr('integrations.nurec.service.asyncio.create_subprocess_exec',launch)
    with TestClient(create_worker(tmp_path/'jobs',TOKEN,grut)) as client:
        response=client.post('/v1/jobs',content=photos(),headers=HEADERS)
        assert response.status_code==202,response.text
        key=response.json()['id']
        for _ in range(100):
            state=client.get('/v1/jobs/'+key,headers=HEADERS).json()
            if state['status']=='ready':break
            time.sleep(.01)
        assert state['status']=='ready',state
        assert len(commands)==4
        assert commands[0][1]=='feature_extractor' and commands[2][1]=='mapper'
        assert 'export_usdz.apply_normalizing_transform=false' in commands[-1]
        artifact=client.get('/v1/jobs/'+key+'/artifact',headers=HEADERS)
        assert artifact.status_code==200 and artifact.content.startswith(b'PK')
        assert client.get('/v1/health',headers=HEADERS).json()['active_jobs']==0
