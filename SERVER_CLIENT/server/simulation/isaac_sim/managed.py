"""Managed native cell. Asset catalog is operator-owned, never supplied by an LLM."""
import uuid
import os
import hashlib
from pathlib import Path
from services.api.storage import Storage
from services.validation.registry import read_yaml
from simulation.isaac_sim.scene_assets import compose_scene


class ManagedNativeCell:
    def __init__(self,catalog_path=None):
        self.catalog=read_yaml(Path(catalog_path)) if catalog_path else {'robots':{}}
        self.store=Storage()
        root=Path(catalog_path).resolve().parent if catalog_path else self.store.runtime/'isaac_project_scene'
        root.mkdir(parents=True,exist_ok=True)
        self.folder=root/'managed_scenes';self.cell=None
        self.models={};self.metadata={'engine':'isaac_sim','simulator_version':'6.2.x','physics_available':True,'scene_loading':True,'scene_editing':True,'automatic_scene_transfer':True,'asset_sha256':'unloaded'}
        self.room_root=root/'captured_rooms'
        self.room_root.mkdir(exist_ok=True)
        self.mesh_root=root/'meshes';self.mesh_root.mkdir(exist_ok=True)
        self.metadata['asset_uploading']=True
        self.catalog['meshes']={p.parent.name:str(p) for p in self.mesh_root.glob('*/model.*')}
        self.metadata['room_loading']=os.getenv('ROBOT_IDE_ALLOW_ROOM_UPLOADS')=='1'
        self.catalog['rooms']={p.parent.name:{'usd':str(p),'sha256':p.parent.name} for p in self.room_root.glob('*/scene.usdz') if len(p.parent.name)==64}
    def load_scene(self,request):
        from simulation.isaac_sim.project_scene import prepare_robots
        prepare_robots(request,self.catalog,self.folder/'robot_assets',self.store)
        manifest=compose_scene(request,self.catalog,self.folder/uuid.uuid4().hex,self.store)
        from simulation.isaac_sim.native import NativeCell
        from isaacsim.core.api import World
        if self.cell:self.cell.stop()
        before_unload = getattr(self, 'before_scene_unload', None)
        if before_unload:before_unload()
        # All mutations stay on the Kit main thread. Composition is validated first.
        World.clear_instance()
        try:self.cell=NativeCell(manifest)
        except BaseException:
            self.cell=None;self.models={}
            raise
        self.models=self.cell.models
        self.metadata={**self.cell.metadata,'scene_loading':True,'scene_editing':True,'automatic_scene_transfer':True,'asset_uploading':True,'room_loading':os.getenv('ROBOT_IDE_ALLOW_ROOM_UPLOADS')=='1'}
        self.cell.metadata=self.metadata
    def register_mesh(self,path,digest):
        self.catalog.setdefault('meshes',{})[digest]=str(path)
        if self.cell:self.cell.mesh_assets=self.catalog['meshes']
        return {'asset_id':digest,'registered':True}
    def validate_scene(self,request):
        if self.cell is None:raise ValueError('No native scene is loaded. Switch from built-in to Isaac Sim to transfer the project scene.')
        return self.cell.validate_scene(request)
    def observe(self):
        if self.cell:return self.cell.observe()
        from shared.models.domain import now
        return {'states':{},'objects':[],'measured_at':now(),'simulation_time':0.,'faults':[]}
    def advance(self,positions,dt):return self.cell.advance(positions,dt)
    def reset(self,positions,objects):return self.cell.reset(positions,objects)
    def sync_objects(self,objects):return self.cell.sync_objects(objects)
    def stop(self):
        if self.cell:self.cell.stop()
    def inventory(self):return self.cell.inventory() if self.cell else {'assets':[],'scope':'No scene loaded'}
    def register_room(self,path,digest):
        if not self.metadata.get('room_loading'):raise ValueError('Enable ROBOT_IDE_ALLOW_ROOM_UPLOADS on the managed worker')
        path=Path(path).resolve()
        if path!=self.room_root/digest/'scene.usdz' or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Room asset checksum or path is invalid')
        from services.api.rooms import validate_usdz
        validate_usdz(path)
        self.catalog['rooms'][digest]={'usd':str(path),'sha256':digest}
        return {'asset_id':digest,'registered':True}
