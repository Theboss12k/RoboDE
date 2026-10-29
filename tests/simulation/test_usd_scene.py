import math
import pytest
from services.validation.registry import read_yaml


def test_native_feedback_limits_preserve_raw_solver_slop_and_reject_larger_excursions(model):
    from simulation.isaac_sim.contracts import bounded_feedback
    from services.validation.registry import validate_positions
    measured={k:spec['min'] for k,spec in model['actuators']['actuators'].items()}
    measured['gripper']=.0800023
    positions,corrections=bounded_feedback(model,measured)
    assert positions['gripper']==.08 and measured['gripper']==.0800023
    assert corrections=={'gripper':{'measured':.0800023,'reported':.08}}
    validate_positions(model,positions)
    with pytest.raises(ValueError):validate_positions(model,measured)
    measured['gripper']=.08002
    positions,corrections=bounded_feedback(model,measured)
    assert not corrections and positions==measured
    with pytest.raises(ValueError):validate_positions(model,positions)


def test_faulted_native_stop_never_queries_invalid_physics_handles():
    pytest.importorskip('numpy')
    from simulation.isaac_sim.native import NativeCell
    cell=NativeCell.__new__(NativeCell);cell.scene_fault='Native handles invalidated'
    paused=[]
    cell.world=type('World',(),{'pause':lambda self:paused.append(True)})()
    # No robots/handles exist after a failed topology edit. Stop must still work.
    cell.stop()
    assert paused==[True]


def test_generated_dual_arm_usd_has_real_rigid_bodies_and_drives(tmp_path):
    pytest.importorskip('pxr',reason='Optional offline USD QA; pxr is bundled with Isaac Sim on the worker')
    from pxr import Usd,UsdPhysics
    from simulation.isaac_sim.build_demo_scene import build
    manifest=read_yaml(build('dual_arm_cell',tmp_path/'cell'))
    stage=Usd.Stage.Open(manifest['scene'])
    assert stage.GetMetadata('upAxis')=='Z'
    assert len([p for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)])==2
    joints=[p for p in stage.Traverse() if p.IsA(UsdPhysics.RevoluteJoint) or p.IsA(UsdPhysics.PrismaticJoint)]
    assert len(joints)==10
    for prim in joints:
        joint=UsdPhysics.Joint(prim)
        assert joint.GetBody0Rel().GetTargets()
        assert joint.GetBody1Rel().GetTargets()
    limits=UsdPhysics.RevoluteJoint(stage.GetPrimAtPath('/World/arm_01/shoulder'))
    assert limits.GetLowerLimitAttr().Get()==pytest.approx(math.degrees(-1.5))
    assert stage.GetPrimAtPath('/World/objects/apple').HasAPI(UsdPhysics.RigidBodyAPI)
    assert len(manifest['robots'])==2
    for robot in manifest['robots']:
        root=stage.GetPrimAtPath(robot['prim_path'])
        assert root.GetAttribute('physxArticulation:enabledSelfCollisions').Get() is False


def test_native_model_contract_ignores_ui_availability_but_preserves_joint_validation(store):
    from simulation.isaac_sim.contracts import require_same_model
    from services.planning.kinematics import with_base
    import copy
    _,instances,models,_=store.load_project('apple_transfer')
    model=with_base(models[0],instances[0]);model.pop('planning_supported',None)
    request={**model,'planning_supported':True}
    require_same_model(request,model,'arm_01')
    changed=copy.deepcopy(request)
    changed['actuators']['actuators']['base_yaw']['max']=1.
    with pytest.raises(ValueError,match='BOT definition differs'):require_same_model(changed,model,'arm_01')


def test_managed_usd_references_approved_robot_and_composes_scene_objects(store,tmp_path):
    pytest.importorskip('pxr')
    import hashlib
    from pxr import Usd,UsdGeom,UsdPhysics
    from shared.models.worker import ConnectRequest
    from services.planning.kinematics import with_base
    from simulation.isaac_sim.scene_assets import compose_scene
    asset=tmp_path/'robot.usda';s=Usd.Stage.CreateNew(str(asset));root=UsdGeom.Xform.Define(s,'/Robot');s.SetDefaultPrim(root.GetPrim());UsdPhysics.ArticulationRootAPI.Apply(root.GetPrim());s.GetRootLayer().Save()
    _,instances,models,objects=store.load_project('apple_transfer')
    request=ConnectRequest(project_id='apple_transfer',robots=[{'instance':instances[0],'model':with_base(models[0],instances[0])}],objects=objects)
    catalog={'robots':{'demo_arm':{'usd':str(asset),'sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'joints':{k:k for k in models[0]['actuators']['actuators']}}}}
    manifest=read_yaml(compose_scene(request,catalog,tmp_path/'out',store));stage=Usd.Stage.Open(manifest['scene'])
    assert stage.GetPrimAtPath('/World/Robots/arm_01').HasAPI(UsdPhysics.ArticulationRootAPI)
    assert stage.GetPrimAtPath('/World/Objects/apple').HasAPI(UsdPhysics.RigidBodyAPI)
    assert stage.GetPrimAtPath('/World/Objects/apple').IsA(UsdGeom.Sphere)
    apple=next(o for o in objects if o.id=='apple')
    bound=UsdGeom.BBoxCache(0,[UsdGeom.Tokens.default_]).ComputeWorldBound(stage.GetPrimAtPath('/World/Objects/apple')).ComputeAlignedRange()
    assert list(bound.GetSize())==pytest.approx([apple.size.x,apple.size.y,apple.size.z])
    assert not stage.GetPrimAtPath('/World/Objects/basket').HasAPI(UsdPhysics.RigidBodyAPI)
    assert stage.GetPrimAtPath('/World/Ground').HasAPI(UsdPhysics.CollisionAPI)
    assert manifest['managed_objects'] and manifest['robots'][0]['joints']['elbow']=='elbow'
    catalog['robots']['demo_arm']['sha256']='bad'
    with pytest.raises(ValueError,match='checksum'):compose_scene(request,catalog,tmp_path/'rejected',store)
    assert not (tmp_path/'rejected').exists()


def test_automatic_project_scene_builds_demo_robots_without_catalog(store,tmp_path):
    pytest.importorskip('pxr')
    from pxr import Usd,UsdPhysics
    from simulation.isaac_sim.project_scene import prepare_robots
    from simulation.isaac_sim.scene_assets import compose_scene
    from shared.models.worker import ConnectRequest
    from services.planning.kinematics import with_base
    _,instances,models,objects=store.load_project('apple_transfer')
    request=ConnectRequest(project_id='apple_transfer',robots=[{'instance':instances[0],'model':with_base(models[0],instances[0])}],objects=objects)
    catalog={'robots':{}}
    prepare_robots(request,catalog,tmp_path/'assets',store)
    assert catalog['robots']['demo_arm']['provenance']=='generated_educational_demo'
    manifest=read_yaml(compose_scene(request,catalog,tmp_path/'scene',store));stage=Usd.Stage.Open(manifest['scene'])
    robot=manifest['robots'][0]
    assert stage.GetPrimAtPath(robot['prim_path']).HasAPI(UsdPhysics.ArticulationRootAPI)
    assert len([p for p in stage.Traverse() if p.IsA(UsdPhysics.RevoluteJoint)])==4
    assert stage.GetPrimAtPath('/World/Objects/apple')


def test_imported_mesh_transfer_preserves_geometry_bounds_and_checksums(tmp_path):
    pytest.importorskip('pxr');pytest.importorskip('trimesh')
    import hashlib
    from pxr import Usd,UsdGeom,UsdPhysics
    from shared.models.domain import WorldObject
    from simulation.isaac_sim.mesh_assets import geometry,add_mesh
    path=tmp_path/'shape.obj';path.write_text('v 0 0 0\nv 2 0 0\nv 0 3 0\nv 0 0 4\nf 1 2 3\nf 1 2 4\nf 1 3 4\nf 2 3 4\n')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    item=WorldObject(id='mesh_part',name='Imported part',kind='object',position={'x':1,'y':2,'z':3},size={'x':.2,'y':.3,'z':.4},mesh={'asset_id':digest,'format':'obj','filename':'shape.obj','up_axis':'Y'})
    parts=geometry(item,path)
    import numpy as np
    vertices=np.concatenate([p[0] for p in parts])
    assert vertices.min(axis=0)==pytest.approx([-.1,-.15,-.2])
    assert vertices.max(axis=0)==pytest.approx([.1,.15,.2])
    stage=Usd.Stage.CreateNew(str(tmp_path/'mesh.usda'));root=add_mesh(stage,item,parts)
    assert stage.GetPrimAtPath(root).HasAPI(UsdPhysics.RigidBodyAPI)
    assert stage.GetPrimAtPath(root+'/Visual_0').IsA(UsdGeom.Mesh)
    assert stage.GetPrimAtPath(root+'/CollisionBounds').HasAPI(UsdPhysics.CollisionAPI)
    path.write_text('altered')
    with pytest.raises(ValueError,match='checksum'):geometry(item,path)


@pytest.mark.parametrize('format',['glb','gltf','obj','stl'])
def test_static_mesh_formats_keep_configured_z_up_geometry(format,tmp_path):
    trimesh=pytest.importorskip('trimesh')
    import hashlib
    import numpy as np
    from shared.models.domain import WorldObject
    from simulation.isaac_sim.mesh_assets import geometry
    source=trimesh.creation.box(extents=[1,2,3])
    exported=source.export(file_type=format,**({'embed_buffers':True} if format=='gltf' else {}))
    if isinstance(exported,dict):exported=exported['model.gltf']
    if isinstance(exported,str):exported=exported.encode()
    path=tmp_path/('model.'+format);path.write_bytes(exported)
    item=WorldObject(id='part',name='Part',kind='obstacle',position={'x':0,'y':0,'z':1},size={'x':.1,'y':.2,'z':.3},mesh={'asset_id':hashlib.sha256(exported).hexdigest(),'format':format,'filename':path.name,'up_axis':'Z'})
    parts=geometry(item,path);vertices=np.concatenate([p[0] for p in parts])
    assert vertices.min(axis=0)==pytest.approx([-.05,-.1,-.15])
    assert vertices.max(axis=0)==pytest.approx([.05,.1,.15])


def test_captured_room_reference_and_named_inventory_preserve_tracked_assets(store,tmp_path):
    pytest.importorskip('pxr')
    import hashlib
    from pxr import Usd,UsdGeom,UsdPhysics,UsdUtils
    from shared.models.worker import ConnectRequest,RoomReference
    from simulation.isaac_sim.scene_assets import compose_scene
    from simulation.isaac_sim.inventory import scene_inventory
    from services.planning.kinematics import with_base
    robot=tmp_path/'robot.usda';stage=Usd.Stage.CreateNew(str(robot));root=UsdGeom.Xform.Define(stage,'/Robot');stage.SetDefaultPrim(root.GetPrim());UsdGeom.Cube.Define(stage,'/Robot/body').CreateSizeAttr(.1);UsdPhysics.ArticulationRootAPI.Apply(root.GetPrim());stage.GetRootLayer().Save()
    scan=tmp_path/'scan.usda';stage=Usd.Stage.CreateNew(str(scan));root=UsdGeom.Xform.Define(stage,'/Room');stage.SetDefaultPrim(root.GetPrim());UsdGeom.Cube.Define(stage,'/Room/walls');stage.GetRootLayer().Save()
    package=tmp_path/'room.usdz';assert UsdUtils.CreateNewUsdzPackage(str(scan),str(package))
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    _,instances,models,objects=store.load_project('apple_transfer')
    model=with_base(models[0],instances[0])
    request=ConnectRequest(project_id='apple_transfer',robots=[{'instance':instances[0],'model':model}],objects=objects,room=RoomReference(asset_id=digest,name='Packaging room',metres_per_unit=.5,translation={'x':1,'y':0,'z':0},yaw_degrees=90))
    catalog={'robots':{'demo_arm':{'usd':str(robot),'sha256':hashlib.sha256(robot.read_bytes()).hexdigest(),'joints':{k:k for k in model['actuators']['actuators']}}},'rooms':{digest:{'usd':str(package)}}}
    manifest=read_yaml(compose_scene(request,catalog,tmp_path/'composed',store));stage=Usd.Stage.Open(manifest['scene'])
    assert stage.GetRootLayer().realPath.endswith('.usda')
    room=stage.GetPrimAtPath('/World/CapturedRoom')
    assert room.HasAuthoredReferences() and room.GetDisplayName()=='Packaging room'
    assert not room.HasAPI(UsdPhysics.CollisionAPI)
    inventory=scene_inventory(stage,{'arm_01':model},{'arm_01':instances[0]},objects,{'arm_01':'/World/Robots/arm_01'},manifest['object_prims'])
    assets=inventory['assets'];assert {'Apple','Basket','Packaging room','Atlas / Arm 01'}<={a['name'] for a in assets}
    apple=next(a for a in assets if a['id']=='apple');assert apple['planning_id']=='apple' and not apple['read_only']
    captured=next(a for a in assets if a['name']=='Packaging room');assert captured['read_only'] and captured['planning_id'] is None
    catalog['rooms'][digest]['usd']=str(scan)
    with pytest.raises(ValueError,match='checksum'):compose_scene(request,catalog,tmp_path/'bad-room',store)
    assert not (tmp_path/'bad-room').exists()

def test_demo_gripper_joint_reports_clear_aperture_and_fingertips_clear_floor(tmp_path):
    pytest.importorskip('pxr')
    from pxr import Usd,UsdGeom,UsdPhysics
    from simulation.isaac_sim.build_demo_scene import build
    manifest=read_yaml(build('apple_transfer',tmp_path/'cell'))
    stage=Usd.Stage.Open(manifest['scene']);root=manifest['robots'][0]['prim_path']
    cache=UsdGeom.BBoxCache(0,[UsdGeom.Tokens.default_])
    left=cache.ComputeWorldBound(stage.GetPrimAtPath(root+'/tool/left_finger')).ComputeAlignedBox()
    right=cache.ComputeWorldBound(stage.GetPrimAtPath(root+'/right_finger/collider')).ComputeAlignedBox()
    opening=UsdPhysics.DriveAPI(stage.GetPrimAtPath(root+'/gripper'),'linear').GetTargetPositionAttr().Get()
    assert right.GetMin()[1]-left.GetMax()[1]==pytest.approx(opening,abs=1e-6)
    # At an object's resting centre, neither 50 mm finger intersects the floor.
    finger_height=left.GetMax()[2]-left.GetMin()[2]
    assert .065/2-finger_height/2>0
    forearm=cache.ComputeWorldBound(stage.GetPrimAtPath(root+'/forearm/collider')).ComputeAlignedBox()
    tcp=UsdGeom.XformCache().GetLocalToWorldTransform(stage.GetPrimAtPath(root+'/tool')).ExtractTranslation()
    assert tcp[0]-forearm.GetMax()[0]>=.069

def test_native_waypoints_include_bounded_velocity_feedforward_and_stop_clears_it(model,instance):
    np=pytest.importorskip('numpy')
    from simulation.isaac_sim.native import NativeCell
    q=instance['initial_configuration']['actuator_positions'];calls=[]
    class Robot:
        def set_joint_position_targets(self,values,**kw):calls.append(('position',values.copy()))
        def set_joint_velocity_targets(self,values,**kw):calls.append(('velocity',values.copy()))
        def get_joint_positions(self,**kw):return np.array([list(q.values())])
    cell=NativeCell.__new__(NativeCell);cell.scene_fault=None;cell.dt=1/120;cell.simulation_time=0.
    cell.models={'arm_01':model};cell.indices={'arm_01':np.arange(len(q))};cell.robots={'arm_01':Robot()}
    cell.world=type('World',(),{'step':lambda self,**kw:None})()
    cell.target_positions={'arm_01':dict(q)}
    cell.observe=lambda:{'states':{'arm_01':{'stopped':True}}}
    moving={**q,'base_yaw':q['base_yaw']+.1}
    cell.advance({'arm_01':moving},1/30)
    assert calls[0][0]=='position' and calls[1][0]=='velocity'
    yaw=list(q).index('base_yaw')
    assert calls[1][1][0,yaw]>0
    assert calls[1][1][0,yaw]<=model['actuators']['actuators']['base_yaw']['velocity']
    cell.stop()
    assert np.array_equal(calls[-1][1],np.zeros((1,len(q))))
    before=len(calls)
    with pytest.raises(ValueError,match='integer multiple'):cell.advance({'arm_01':moving},.001)
    assert len(calls)==before
