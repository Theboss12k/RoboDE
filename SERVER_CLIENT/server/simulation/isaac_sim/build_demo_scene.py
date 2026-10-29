"""Generate a self-contained educational USD cell from the registered demo models.

Run with Isaac Sim's Python (pxr included), or install usd-core for offline USD QA.
This asset is not a manufacturer model and has not been physics-tuned on this Mac.
"""
import argparse
import hashlib
import math
from pathlib import Path
import yaml
from services.api.storage import Storage
from services.validation.registry import ROOT


def build(project_id,output,scene_data=None):
    from pxr import Usd,UsdGeom,UsdPhysics,UsdShade,Gf,Sdf
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    scene=output/'cell.usda'
    stage=Usd.Stage.CreateNew(str(scene))
    UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage,1.)
    world=UsdGeom.Xform.Define(stage,'/World')
    stage.SetDefaultPrim(world.GetPrim())
    physics=UsdPhysics.Scene.Define(stage,'/World/Physics')
    physics.CreateGravityDirectionAttr(Gf.Vec3f(0,0,-1))
    physics.CreateGravityMagnitudeAttr(9.81)
    material=UsdShade.Material.Define(stage,'/World/GripMaterial')
    mat=UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    mat.CreateStaticFrictionAttr(1.4)
    mat.CreateDynamicFrictionAttr(1.1)
    mat.CreateRestitutionAttr(0.)

    def shape(path,position,size,color=(.55,.65,.45)):
        cube=UsdGeom.Cube.Define(stage,path)
        cube.CreateSizeAttr(1.)
        x=UsdGeom.Xformable(cube)
        x.AddTranslateOp().Set(Gf.Vec3d(*position))
        x.AddScaleOp().Set(Gf.Vec3f(*size))
        cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        cube.GetPrim().AddAppliedSchema('PhysxCollisionAPI')
        cube.GetPrim().CreateAttribute('physxCollision:contactOffset',Sdf.ValueTypeNames.Float).Set(.001)
        cube.GetPrim().CreateAttribute('physxCollision:restOffset',Sdf.ValueTypeNames.Float).Set(0.)
        UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(material,UsdShade.Tokens.weakerThanDescendants,'physics')
        return cube

    def body(path,position,mass):
        prim=UsdGeom.Xform.Define(stage,path)
        prim.AddTranslateOp().Set(Gf.Vec3d(*position))
        UsdPhysics.RigidBodyAPI.Apply(prim.GetPrim())
        UsdPhysics.MassAPI.Apply(prim.GetPrim()).CreateMassAttr(mass)
        return prim

    def joint(path,parent,child,position,axis,limit,angular=True,flip=False,target=0.):
        cls=UsdPhysics.RevoluteJoint if angular else UsdPhysics.PrismaticJoint
        j=cls.Define(stage,path)
        j.CreateBody0Rel().SetTargets([parent])
        j.CreateBody1Rel().SetTargets([child])
        j.CreateLocalPos0Attr(Gf.Vec3f(*position))
        j.CreateLocalPos1Attr(Gf.Vec3f(0,0,0))
        if flip:
            j.CreateLocalRot0Attr(Gf.Quatf(0.,Gf.Vec3f(1,0,0)))
            j.CreateLocalRot1Attr(Gf.Quatf(0.,Gf.Vec3f(1,0,0)))
        j.CreateAxisAttr(axis)
        conversion=180/math.pi if angular else 1.
        j.CreateLowerLimitAttr(limit['min']*conversion)
        j.CreateUpperLimitAttr(limit['max']*conversion)
        j.CreateCollisionEnabledAttr(False)
        drive=UsdPhysics.DriveAPI.Apply(j.GetPrim(),'angular' if angular else 'linear')
        drive.CreateTypeAttr('force')
        drive.CreateStiffnessAttr(1500. if angular else 2500.)
        drive.CreateDampingAttr(100. if angular else 80.)
        drive.CreateMaxForceAttr(150. if angular else 15.)
        drive.CreateTargetPositionAttr(target*conversion)
        return j

    shape('/World/Table',(0,0,-.025),(8,8,.05),(.25,.3,.25))
    project,instances,models,objects=scene_data if scene_data is not None else Storage().load_project(project_id)
    manifest_robots=[]
    for instance,model in zip(instances,models):
        rid=instance['instance']['id']
        root=f'/World/{rid}'
        base=instance.get('base_pose',dict(x=0.,y=0.,z=0.,yaw=0.))
        group=UsdGeom.Xform.Define(stage,root)
        group.AddTranslateOp().Set(Gf.Vec3d(base['x'],base['y'],base['z']))
        group.AddRotateZOp().Set(math.degrees(base['yaw']))
        UsdPhysics.ArticulationRootAPI.Apply(group.GetPrim())
        # The educational model uses overlapping box proxies at its joints.
        # Disable internal proxy contacts while retaining contacts with the scene.
        # Author the PhysX schema as USD data so offline usd-core can build it too.
        group.GetPrim().AddAppliedSchema('PhysxArticulationAPI')
        group.GetPrim().CreateAttribute('physxArticulation:enabledSelfCollisions',Sdf.ValueTypeNames.Bool).Set(False)
        group.GetPrim().CreateAttribute('physxArticulation:solverPositionIterationCount',Sdf.ValueTypeNames.Int).Set(64)
        group.GetPrim().CreateAttribute('physxArticulation:solverVelocityIterationCount',Sdf.ValueTypeNames.Int).Set(8)
        h,a,b=(model['kinematics']['links'][k] for k in ('base_height','upper_arm','forearm'))
        body(root+'/base',(0,0,0),3.)
        shape(root+'/base/collider',(0,0,h/2),(.1,.1,h))
        body(root+'/yaw_link',(0,0,h),.4)
        shape(root+'/yaw_link/collider',(0,0,0),(.06,.06,.045))
        body(root+'/upper',(0,0,h),1.)
        shape(root+'/upper/collider',(a/2,0,0),(a,.035,.035))
        body(root+'/forearm',(a,0,h),.7)
        # Keep the forearm proxy outside the open jaws. Extending it to
        # the TCP puts solid arm geometry inside the object being grasped.
        forearm_length=max(.01,b-.07)
        shape(root+'/forearm/collider',(forearm_length/2,0,0),(forearm_length,.032,.032))
        body(root+'/tool',(a+b,0,h),.25)
        shape(root+'/tool/palm',(0,0,.05),(.04,.09,.02))
        # Joint displacement is the clear jaw opening in metres, not the
        # distance between collider centres. Keep fingertips above the floor
        # when the TCP reaches the centre of a 65 mm demonstration object.
        shape(root+'/tool/left_finger',(0,-.044,0),(.035,.008,.05))
        body(root+'/right_finger',(a+b,.044,h),.08)
        shape(root+'/right_finger/collider',(0,0,0),(.035,.008,.05))
        fixed=UsdPhysics.FixedJoint.Define(stage,root+'/fixed_base')
        fixed.CreateBody1Rel().SetTargets([root+'/base'])
        limits=model['actuators']['actuators']
        joint(root+'/base_yaw',root+'/base',root+'/yaw_link',(0,0,h),'Z',limits['base_yaw'])
        joint(root+'/shoulder',root+'/yaw_link',root+'/upper',(0,0,0),'Y',limits['shoulder'],flip=True)
        joint(root+'/elbow',root+'/upper',root+'/forearm',(a,0,0),'Y',limits['elbow'],flip=True)
        joint(root+'/wrist',root+'/forearm',root+'/tool',(b,0,0),'Y',limits['wrist'],flip=True)
        joint(root+'/gripper',root+'/tool',root+'/right_finger',(0,-.036,0),'Y',limits['gripper'],angular=False,target=.08)
        instance_file=output/f'{rid}.yaml'
        instance_file.write_text(yaml.safe_dump(instance,sort_keys=False))
        manifest_robots.append({'instance_file':str(instance_file),'prim_path':root,'joints':{k:k for k in limits}})
    object_prims={}
    for item in objects:
        path=f'/World/objects/{item.id}'
        object_prims[item.id]=path
        group=UsdGeom.Xform.Define(stage,path)
        group.AddTranslateOp().Set(Gf.Vec3d(item.position.x,item.position.y,item.position.z))
        sx,sy,sz=item.size.x,item.size.y,item.size.z
        if item.kind=='object':
            UsdPhysics.RigidBodyAPI.Apply(group.GetPrim())
            UsdPhysics.MassAPI.Apply(group.GetPrim()).CreateMassAttr(item.mass_kg)
            sphere=UsdGeom.Sphere.Define(stage,path+'/collider')
            sphere.CreateRadiusAttr(max(sx,sy,sz)/2)
            sphere.CreateDisplayColorAttr([Gf.Vec3f(.7,.16,.08)])
            UsdPhysics.CollisionAPI.Apply(sphere.GetPrim())
            UsdShade.MaterialBindingAPI.Apply(sphere.GetPrim()).Bind(material,UsdShade.Tokens.weakerThanDescendants,'physics')
        elif item.kind=='region':
            shape(path+'/floor',(0,0,-sz/2+.005),(sx,sy,.01),(.65,.5,.25))
            for sign in (-1,1):
                suffix='p' if sign>0 else 'n'
                shape(path+f'/wall_x_{suffix}',(sign*sx/2,0,0),(.01,sy,sz),(.65,.5,.25))
                shape(path+f'/wall_y_{suffix}',(0,sign*sy/2,0),(sx, .01,sz),(.65,.5,.25))
        else:
            shape(path+'/collider',(0,0,0),(sx,sy,sz),(.6,.4,.25))
    stage.GetRootLayer().Save()
    manifest={'scene':str(scene),'scene_sha256':hashlib.sha256(scene.read_bytes()).hexdigest(),'physics_dt':1/120,
              'robots':manifest_robots,'objects':[o.model_dump() for o in objects],'object_prims':object_prims}
    path=output/'worker.yaml'
    path.write_text(yaml.safe_dump(manifest,sort_keys=False))
    return path


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',default='dual_arm_cell')
    p.add_argument('--output',default='robot_system/runtime/isaac_cell')
    a=p.parse_args()
    print(build(a.project,a.output))
