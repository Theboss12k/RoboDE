import io
import zipfile
from fastapi.testclient import TestClient
from services.api.main import create_app


def usdz(name='room.usda'):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_STORED) as archive:archive.writestr(name,'#usda 1.0\n(defaultPrim="Room")\ndef Xform "Room" {}')
    return data.getvalue()


def test_capture_upload_reconstruction_requirements_and_scene_import(store,monkeypatch):
    monkeypatch.delenv('NUREC_WORKER_URL',raising=False);monkeypatch.delenv('NUREC_WORKER_TOKEN',raising=False)
    with TestClient(create_app(store)) as client:
        base='/api/business/projects/apple_transfer/rooms'
        room=client.post(base,json={'name':'Packaging room'}).json();path=base+'/'+room['id']
        assert room['status']=='capture'
        assert client.get(path+'/scene').status_code==409
        assert client.post(path+'/reconstruct').status_code==422
        assert client.put(path+'/photos?filename=bad.jpg',content=b'not an image').status_code==422
        assert client.get(path).json()['photos']==0
        for _ in range(12):assert client.put(path+'/photos?filename=room.jpg',content=b'\xff\xd8\xff'+b'fixture').status_code==201
        # Missing cloud configuration does not discard locally recorded photos.
        assert client.post(path+'/reconstruct').status_code==422
        assert client.get(path).json()['photos']==12
        assert client.put(path+'/scene',content=usdz('../escape.usda')).status_code==422
        imported=client.put(path+'/scene',content=usdz())
        assert imported.status_code==200,imported.text
        assert imported.json()['status']=='align'
        assert client.get(path+'/scene').content==usdz()
        assert client.post(path+'/deploy',json={'metres_per_unit':1,'translation':{'x':0,'y':0,'z':0},'yaw_degrees':0,'reviewed':False,'assets':[dict(id='table',name='Table',kind='obstacle',position=dict(x=0,y=0,z=.5),size=dict(x=1,y=1,z=1),mass_kg=0)]}).status_code==422
        assert not (store.project_folder('apple_transfer')/'environment/room.json').exists()


def test_business_browsing_and_photo_capture_never_wake_gpu(store):
    import yaml
    from services.api.storage import atomic_json
    path=store.project_folder('apple_transfer')/'project.yaml';project=yaml.safe_load(path.read_text());project['simulation']={'adapter':'isaac_sim'};path.write_text(yaml.safe_dump(project))
    atomic_json(store.runtime/'connections/isaac.json',{'on_demand':True,'gcp_project':'test-project','gcp_zone':'test-zone','gcp_instance':'test-vm'})
    app=create_app(store)
    async def forbidden(*args,**kwargs):raise AssertionError('Browsing must not contact or start a GPU VM')
    app.state.controller.gpu.runner=forbidden
    with TestClient(app) as client:
        workspace=client.get('/api/business/projects/apple_transfer/workspace')
        assert workspace.status_code==200,workspace.text
        assert workspace.json()['source']=='configured_preview' and not workspace.json()['connected']
        desktop=client.get('/api/projects/apple_transfer')
        assert desktop.status_code==200,desktop.text
        assert not desktop.json()['environment_connected']
        assert not app.state.controller.sessions
        assert not client.get('/api/business/rooms/status').json()['ready']
        base='/api/business/projects/apple_transfer/rooms'
        room=client.post(base,json={'name':'Phone capture'}).json()
        assert client.put(base+'/'+room['id']+'/photos?filename=room.jpg',content=b'\xff\xd8\xffphoto').status_code==201
        assert app.state.controller.gpu.task is None
