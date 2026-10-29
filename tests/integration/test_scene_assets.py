import base64
import json
import struct
import pytest
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.api.assets import validate_asset
from shared.models.domain import WorldObject,Pose,Frame
from services.validation.trajectory import validate_trajectory

OBJ = b'v -1 -1 -1\nv 1 -1 -1\nv 0 1 1\nf 1 2 3\n'
STL = b'solid test\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 1\nendloop\nendfacet\nendsolid test\n'


def upload(client,project='apple_transfer',name='shape.obj',data=OBJ):
    return client.post(f'/api/projects/{project}/assets',params={'filename':name},content=data,headers={'Content-Type':'application/octet-stream'})


def test_asset_save_render_reference_reset_and_clone_preserve_file(store):
    with TestClient(create_app(store)) as client:
        before=client.get('/api/projects/apple_transfer').json()
        response=upload(client)
        assert response.status_code==201,response.text
        asset=response.json()
        item={'id':'custom_mesh','name':'Custom mesh','kind':'obstacle','position':{'x':.3,'y':.5,'z':.1},'size':{'x':.15,'y':.15,'z':.15},'mass_kg':0,
              'mesh':{'asset_id':asset['id'],'format':'obj','filename':'shape.obj','up_axis':'Y'}}
        objects=before['objects']+[item]
        saved=client.put('/api/projects/apple_transfer/world',json={'objects':objects})
        assert saved.status_code==200,saved.text
        assert client.get('/api/projects/apple_transfer').json()['objects'][-1]['mesh']['asset_id']==asset['id']
        assert client.get(f"/api/projects/apple_transfer/assets/{asset['id']}").content==OBJ
        assert client.post('/api/projects/apple_transfer/reset').status_code==200
        assert client.get('/api/projects/apple_transfer').json()['objects'][-1]['mesh']['asset_id']==asset['id']
        clone=client.post('/api/projects',json={'name':'Model clone','source':'apple_transfer'}).json()
        assert client.get(f"/api/projects/{clone['id']}/assets/{asset['id']}").content==OBJ
        assert client.get(f"/api/projects/{clone['id']}").json()['objects'][-1]['mesh']['format']=='obj'
        assert upload(client).json()['id']==asset['id']
    # A new runtime must restore the mesh reference as well as its geometry.
    with TestClient(create_app(store)) as client:
        assert client.get('/api/projects/apple_transfer').json()['objects'][-1]['mesh']['asset_id']==asset['id']


def test_invalid_model_references_do_not_change_saved_or_live_world(store):
    with TestClient(create_app(store)) as client:
        before=client.get('/api/projects/apple_transfer').json()['objects']
        broken={**before[0],'id':'broken','mesh':{'asset_id':'0'*64,'format':'obj','filename':'missing.obj','up_axis':'Y'}}
        response=client.put('/api/projects/apple_transfer/world',json={'objects':before+[broken]})
        assert response.status_code in {404,422}
        assert client.get('/api/projects/apple_transfer').json()['objects']==before
        asset=upload(client).json()
        broken['mesh'].update(asset_id=asset['id'],format='stl')
        assert client.put('/api/projects/apple_transfer/world',json={'objects':before+[broken]}).status_code==422
        assert client.get('/api/projects/apple_transfer').json()['objects']==before


def test_upload_rejects_invalid_files_and_external_gltf_resources(store):
    with TestClient(create_app(store)) as client:
        for name,data in [('virus.py',b'print(1)'),('bad.glb',b'not a model'),('bad.obj',b'no geometry'),('bad.stl',b'solid nope')]:
            assert upload(client,name=name,data=data).status_code==422
        document={'asset':{'version':'2.0'},'meshes':[{}],'buffers':[{'uri':'https://example.com/private.bin'}]}
        response=upload(client,name='external.gltf',data=json.dumps(document).encode())
        assert response.status_code==422 and 'self-contained' in response.text
        assert client.get('/api/projects/apple_transfer/assets/..%2Fproject.yaml').status_code in {404,422}
        assert upload(client,name='shape.stl',data=STL).status_code==201


def test_file_limit_and_isaac_import_boundary(store,monkeypatch):
    from services.api import assets
    monkeypatch.setattr(assets,'MAX_ASSET_BYTES',32)
    with TestClient(create_app(store)) as client:
        assert upload(client,data=OBJ*2).status_code==413
        import yaml
        path=store.project_folder('apple_transfer')/'project.yaml'
        project=yaml.safe_load(path.read_text());project['simulation']={'adapter':'isaac_sim'};path.write_text(yaml.safe_dump(project))
        response=upload(client)
        assert response.status_code==422 and 'updated managed Isaac worker' in response.text


def test_glb_and_embedded_gltf_validation():
    document={'asset':{'version':'2.0'},'meshes':[{'primitives':[]}],'buffers':[{'uri':'data:application/octet-stream;base64,AAAA','byteLength':3}]}
    raw=json.dumps(document).encode()
    validate_asset(raw,'gltf')
    padded=raw+b' '*((-len(raw))%4)
    glb=struct.pack('<4sIIII',b'glTF',2,20+len(padded),len(padded),0x4E4F534A)+padded
    validate_asset(glb,'glb')
    with pytest.raises(ValueError):validate_asset(glb[:-1],'glb')
    document['extensionsRequired']=['KHR_draco_mesh_compression']
    with pytest.raises(ValueError,match='uncompressed'):validate_asset(json.dumps(document).encode(),'gltf')


def test_flat_object_table_clearance_uses_height_not_width(model,instance):
    item=WorldObject(id='wide_flat',name='Flat part',kind='object',position=Pose(x=.3,y=.3,z=.02),size=Pose(x=.2,y=.2,z=.02))
    frames=[Frame(time=t,step_id='hold',positions=instance['initial_configuration']['actuator_positions'],objects={item.id:item.position}) for t in (0,1)]
    validate_trajectory(model,frames,[item])
