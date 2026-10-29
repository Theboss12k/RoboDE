"""Authenticated transfer protocol, without claiming native physics validation."""
import hashlib
import httpx
import pytest
from scripts.contract_scene import ContractScene
from shared.models.domain import WorldObject
from services.planning.kinematics import with_base
from simulation.isaac_sim.worker import create_worker
from robot_system.registry.models.demo_arm.adapters.isaac_sim.adapter import IsaacCell

TOKEN='private-scene-transfer-contract'


async def test_handoff_initializes_once_and_lease_reconnect_only_observes(store,model,instance):
    backend=ContractScene();worker=create_worker(backend,TOKEN)
    client=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker),base_url='http://worker',headers={'Authorization':'Bearer '+TOKEN})
    objects=store.load_project('apple_transfer')[-1]
    q={**instance['initial_configuration']['actuator_positions'],'base_yaw':.7}
    cell=IsaacCell('apple_transfer',[instance],{'arm_01':with_base(model,instance)},objects,client=client,require_native=False,load_scene=True,transfer_positions={'arm_01':q})
    await cell.connect()
    assert cell.latest.states['arm_01'].positions==q and backend.resets==1
    assert len(backend.loads)==1
    await client.delete('/v1/sessions/'+cell.session_id)
    await cell.connect()
    assert len(backend.loads)==1 and backend.resets==1
    assert cell.latest.states['arm_01'].positions==q
    await cell.disconnect()


async def test_transfer_assets_are_authenticated_bounded_and_checksum_verified(store,model,instance,tmp_path,monkeypatch):
    backend=ContractScene();backend.mesh_root=tmp_path/'meshes';backend.mesh_root.mkdir()
    backend.metadata={**backend.metadata,'asset_uploading':True}
    registered={}
    def register(path,digest):registered[digest]=path;return {'asset_id':digest}
    backend.register_mesh=register
    worker=create_worker(backend,TOKEN)
    client=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker),base_url='http://worker',headers={'Authorization':'Bearer '+TOKEN})
    raw=b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n';digest=hashlib.sha256(raw).hexdigest()
    source=tmp_path/'mesh.obj';source.write_bytes(raw)
    item=WorldObject(id='part',name='Part',kind='obstacle',position={'x':1,'y':1,'z':1},size={'x':1,'y':1,'z':1},mesh={'asset_id':digest,'format':'obj','filename':'mesh.obj'})
    cell=IsaacCell('apple_transfer',[instance],{'arm_01':with_base(model,instance)},[item],client=client,require_native=False,load_scene=True)
    cell.asset_provider=lambda _:({'format':'obj'},source)
    await cell.connect()
    assert registered[digest].read_bytes()==raw and backend.objects==[item]
    assert (await client.put('/v1/scene-assets/meshes/'+digest+'?format=obj',content=b'bad')).status_code==422
    assert registered[digest].read_bytes()==raw
    assert (await client.put('/v1/scene-assets/meshes/'+digest+'?format=obj',content=raw,headers={'Authorization':'Bearer invalid'})).status_code==401
    from services.api import assets
    monkeypatch.setattr(assets,'MAX_ASSET_BYTES',8)
    assert (await client.put('/v1/scene-assets/meshes/'+digest+'?format=obj',content=raw)).status_code==413
    assert registered[digest].read_bytes()==raw
    assert not list(backend.mesh_root.rglob('*.tmp'))
    await cell.disconnect()


async def test_invalid_transfer_positions_do_not_load_or_reset_scene(model,instance):
    backend=ContractScene();worker=create_worker(backend,TOKEN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=worker),base_url='http://worker',headers={'Authorization':'Bearer '+TOKEN}) as client:
        body={'load_scene':True,'project_id':'apple_transfer','robots':[{'instance':instance,'model':with_base(model,instance)}],'objects':[],
            'transfer_positions':{'arm_01':{**instance['initial_configuration']['actuator_positions'],'elbow':999}}}
        assert (await client.post('/v1/sessions',json=body)).status_code==422
        assert backend.resets==0 and not backend.loads
