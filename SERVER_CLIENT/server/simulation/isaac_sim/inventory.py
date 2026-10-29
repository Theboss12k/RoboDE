"""Named scene assets for the business UI. Runs only on the native Kit main thread."""
import math

def scene_inventory(stage,models,instances,objects,robot_paths,object_paths):
    from pxr import UsdGeom,Usd
    known={object_paths[o.id]:('asset',o.id,o.name,o.kind) for o in objects}
    known.update({robot_paths[r]:('robot',r,instances[r]['instance']['name'],'robot') for r in models})
    cache=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render],useExtentsHint=True)
    result=[];roots=[]
    for prim in stage.Traverse():
        path=str(prim.GetPath())
        if not prim.IsActive() or not prim.IsA(UsdGeom.Imageable) or any(path.startswith(p+'/') for p in roots):continue
        mapped=known.get(path)
        if not mapped and prim.HasAuthoredReferences():mapped=next((entry for p,entry in known.items() if entry[0]=='robot' and p.startswith(path+'/')),None)
        named=prim.GetMetadata('displayName')
        candidate=mapped or named or prim.HasAuthoredReferences() or str(prim.GetParent().GetPath())=='/World'
        if not candidate or path in {'/World','/World/Objects','/World/Robots','/World/Light','/World/Physics'}:continue
        box=cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if box.IsEmpty():continue
        low,high=box.GetMin(),box.GetMax()
        if not all(math.isfinite(v) for v in (*low,*high)):continue
        position={a:float((low[i]+high[i])/2) for i,a in enumerate('xyz')};size={a:max(.001,float(high[i]-low[i])) for i,a in enumerate('xyz')}
        category,pid,name,kind=mapped or ('visual',None,named or prim.GetName(),'obstacle')
        if path in {'/World/Ground','/World/GroundPlane','/World/defaultGroundPlane'}:kind='floor'
        if category=='asset':
            tracked=next(o for o in objects if o.id==pid);position=tracked.position.model_dump();size=tracked.size.model_dump()
        result.append({'id':pid or path,'planning_id':pid if category=='asset' else None,'name':named or name,'kind':kind,'position':position,'size':size,
            'source':'isaac_sim','prim_path':path,'read_only':category!='asset','category':category})
        roots.append(path)
    return {'assets':result,'scope':'Named assets and top-level models from the live Isaac USD stage','geometry':'world bounding boxes; native NuRec rendering stays in Isaac Sim'}
