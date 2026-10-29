"""Compose native USD from an operator-owned, checksum-pinned robot asset catalog.

This module can be tested with usd-core. No Isaac/PhysX imports or remote asset
URLs: upload/convert URDFs on the VM, then approve their USD and DOF mappings.
"""
import hashlib
import re
from pathlib import Path
from shared.models.domain import WorldObject
from simulation.isaac_sim.contracts import require_same_model


def validate_objects(objects,mesh_assets=None):
    if len(objects)>256 or len({o.id for o in objects})!=len(objects):raise ValueError('Scene requires unique object IDs, at most 256')
    for o in objects:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,119}',o.id):raise ValueError('Native object IDs require letters, digits and underscores')
        if o.mesh and (mesh_assets is None or o.mesh.asset_id not in mesh_assets):raise ValueError(f'{o.name}: imported mesh has not been transferred to this worker')
        if any(v<=0 for v in o.size.model_dump().values()):raise ValueError('Object dimensions must be positive')


def add_object(stage,item,mesh_geometry=None):
    if item.mesh:
        from simulation.isaac_sim.mesh_assets import add_mesh
        return add_mesh(stage,item,mesh_geometry)
    from pxr import UsdGeom,UsdPhysics,Gf,Sdf
    path='/World/Objects/'+item.id
    # Match the browser's established apple primitive; other assets retain
    # their box geometry, and imported meshes use their actual triangles.
    apple=item.kind=='object' and (item.id=='apple' or item.id.startswith('apple_'))
    if apple:
        cube=UsdGeom.Sphere.Define(stage,path);cube.CreateRadiusAttr(.5)
    else:
        cube=UsdGeom.Cube.Define(stage,path);cube.CreateSizeAttr(1.)
    cube.GetPrim().SetDisplayName(item.name)
    cube.AddTranslateOp().Set(Gf.Vec3d(*item.position.model_dump().values()))
    cube.AddScaleOp().Set(Gf.Vec3f(*item.size.model_dump().values()))
    cube.CreateDisplayColorAttr().Set([Gf.Vec3f(*({'object':(.8,.3,.16),'region':(.1,.6,.45),'obstacle':(.4,.45,.5)}[item.kind]))])
    if item.kind!='region':
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        # Centimetre-scale grasping needs contact generation at millimetre
        # separation, matching the robot's finger colliders.
        cube.GetPrim().AddAppliedSchema('PhysxCollisionAPI')
        cube.GetPrim().CreateAttribute('physxCollision:contactOffset',Sdf.ValueTypeNames.Float).Set(.001)
        cube.GetPrim().CreateAttribute('physxCollision:restOffset',Sdf.ValueTypeNames.Float).Set(0.)
    if item.kind=='object':
        UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim())
        UsdPhysics.MassAPI.Apply(cube.GetPrim()).CreateMassAttr(max(.001,item.mass_kg))
    return path


def compose_scene(request,catalog,folder,store):
    import yaml
    from pxr import Usd,UsdGeom,UsdPhysics,UsdLux,Gf
    from services.validation.registry import load_model,validate_positions
    from services.planning.kinematics import with_base
    mesh_assets=catalog.get('meshes',{})
    validate_objects(request.objects,mesh_assets)
    from simulation.isaac_sim.mesh_assets import geometry
    mesh_geometry={o.id:geometry(o,mesh_assets[o.mesh.asset_id]) for o in request.objects if o.mesh}
    room_asset=None
    if request.room:
        asset=catalog.get('rooms',{}).get(request.room.asset_id)
        if asset is None:raise ValueError('Captured room is not registered on this worker; deploy its USDZ first')
        room_asset=Path(asset['usd']).resolve()
        if not room_asset.is_file() or hashlib.sha256(room_asset.read_bytes()).hexdigest()!=request.room.asset_id:raise ValueError('Captured room checksum mismatch')
    # Validate every robot and asset before creating or replacing any live stage.
    approved=[];ids=set()
    for entry in request.robots:
        instance=entry['instance'];rid=instance['instance']['id'];mid=instance['robot_model']['id']
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,79}',rid) or rid in ids:raise ValueError('Native robot IDs must be unique USD identifiers')
        ids.add(rid)
        asset=catalog.get('robots',{}).get(mid)
        if asset is None:raise ValueError(f'{mid}: no approved USD asset in worker catalog')
        model=with_base(load_model(store.model_folder(mid)),instance)
        require_same_model(entry['model'],model,rid)
        validate_positions(model,instance['initial_configuration']['actuator_positions'])
        path=Path(asset['usd']).expanduser().resolve()
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha256']:raise ValueError(f'{mid}: approved USD checksum mismatch')
        if set(asset['joints'])!=set(model['actuators']['actuators']):raise ValueError(f'{mid}: incomplete USD joint mapping')
        relative=asset.get('articulation_path','')
        if relative.startswith('/') or '..' in relative.split('/'):raise ValueError('articulation_path must be relative to the referenced root')
        approved.append((instance,model,asset,path))
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    stage=Usd.Stage.CreateNew(str(folder/'cell.usda'));UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z);UsdGeom.SetStageMetersPerUnit(stage,1.)
    root=UsdGeom.Xform.Define(stage,'/World');stage.SetDefaultPrim(root.GetPrim());UsdPhysics.Scene.Define(stage,'/World/Physics')
    if room_asset:
        # Reference a NuRec package under a regular USDA root, never use USDZ as
        # the root stage. Gaussian visuals are separate from authored colliders.
        room=UsdGeom.Xform.Define(stage,'/World/CapturedRoom');room.GetPrim().SetDisplayName(request.room.name)
        room.GetPrim().GetReferences().AddReference(str(room_asset))
        room.AddTranslateOp().Set(Gf.Vec3d(*request.room.translation.model_dump().values()))
        room.AddRotateZOp().Set(request.room.yaw_degrees)
        room.AddScaleOp().Set(Gf.Vec3f(request.room.metres_per_unit))
    UsdLux.DomeLight.Define(stage,'/World/Light').CreateIntensityAttr(1000.)
    ground=WorldObject(id='floor',name='Floor',kind='obstacle',position={'x':0,'y':0,'z':-.05},size={'x':20,'y':20,'z':.1})
    add_object(stage,ground)
    # Floor is outside the editable object namespace.
    from pxr import Sdf
    edit=Sdf.BatchNamespaceEdit();edit.Add('/World/Objects/floor','/World/Ground');stage.GetRootLayer().Apply(edit)
    robots=[]
    for instance,model,asset,path in approved:
        rid=instance['instance']['id'];base=model['base_pose'];mount='/World/Robots/'+rid
        prim=UsdGeom.Xform.Define(stage,mount);prim.GetPrim().GetReferences().AddReference(str(path))
        prim.GetPrim().SetDisplayName(instance['instance']['name'])
        prim.ClearXformOpOrder()
        prim.AddTranslateOp(opSuffix='robot_ide_base').Set(Gf.Vec3d(base['x'],base['y'],base['z']));prim.AddOrientOp(opSuffix='robot_ide_base').Set(Gf.Quatf(__import__('math').cos(base['yaw']/2),Gf.Vec3f(0,0,__import__('math').sin(base['yaw']/2))))
        file=folder/f'{rid}.yaml';file.write_text(yaml.safe_dump(instance,sort_keys=False))
        robots.append({'instance_file':str(file.resolve()),'prim_path':mount+('/'+asset['articulation_path'] if asset.get('articulation_path') else ''),'joints':asset['joints']})
    paths={o.id:add_object(stage,o,mesh_geometry.get(o.id)) for o in request.objects};stage.GetRootLayer().Save()
    file=folder/'cell.usda'
    config={'scene':str(file.resolve()),'scene_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'physics_dt':1/120,
        'robots':robots,'objects':[o.model_dump() for o in request.objects],'object_prims':paths,'managed_objects':True,'mesh_assets':mesh_assets}
    manifest=folder/'worker.yaml';manifest.write_text(yaml.safe_dump(config,sort_keys=False));return manifest
