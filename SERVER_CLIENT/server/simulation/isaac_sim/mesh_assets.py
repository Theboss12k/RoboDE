"""Convert self-contained scene meshes to static Z-up USD geometry, offline.

Only uploaded bytes are parsed: no external files, URLs, scripts or SDK code.
Planning/collision uses the same named bounding box as the built-in simulator.
Texture shaders and animation are intentionally not translated.
"""
import hashlib
import io
from pathlib import Path


def geometry(item,path):
    import numpy as np
    import trimesh
    from services.api.assets import validate_asset
    path=Path(path);data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=item.mesh.asset_id:raise ValueError(f'{item.name}: imported mesh checksum mismatch')
    validate_asset(data,item.mesh.format)
    scene=trimesh.load_scene(io.BytesIO(data),file_type=item.mesh.format,resolver={},allow_remote=False,
        process=False,skip_materials=True)
    parts=[];count=0
    for node in scene.graph.nodes_geometry:
        transform,name=scene.graph[node];source=scene.geometry[name]
        if not isinstance(source,trimesh.Trimesh):continue
        count+=len(source.vertices)
        if count>1000000:raise ValueError('Imported mesh exceeds the one-million-vertex limit')
        vertices=trimesh.transform_points(source.vertices,transform)
        if item.mesh.up_axis=='Y':vertices=vertices[:,[0,2,1]]*np.array([1.,-1.,1.])
        if not np.isfinite(vertices).all():raise ValueError('Imported mesh has invalid vertices')
        faces=np.asarray(source.faces)
        if faces.ndim!=2 or faces.shape[1]!=3 or (faces.size and (faces.min()<0 or faces.max()>=len(vertices))):raise ValueError('Imported mesh has invalid faces')
        if len(faces)>2000000:raise ValueError('Imported mesh exceeds the triangle limit')
        if len(vertices) and len(faces):parts.append((vertices,faces))
    if not parts:raise ValueError('Imported mesh has no renderable triangles')
    vertices=np.concatenate([p[0] for p in parts]);low=vertices.min(axis=0);extent=vertices.max(axis=0)-low
    if extent.max()<1e-9:raise ValueError('Imported mesh has empty bounds')
    centre=low+extent/2;divisor=np.where(extent>1e-9,extent,1.)
    size=np.array([item.size.x,item.size.y,item.size.z])
    return [((v-centre)/divisor*size,f) for v,f in parts]


def add_mesh(stage,item,parts):
    from pxr import UsdGeom,UsdPhysics,Gf
    path='/World/Objects/'+item.id
    root=UsdGeom.Xform.Define(stage,path);root.GetPrim().SetDisplayName(item.name)
    root.AddTranslateOp().Set(Gf.Vec3d(item.position.x,item.position.y,item.position.z))
    for index,(vertices,faces) in enumerate(parts):
        mesh=UsdGeom.Mesh.Define(stage,path+'/Visual_'+str(index))
        mesh.CreatePointsAttr(vertices.tolist());mesh.CreateFaceVertexCountsAttr([3]*len(faces))
        mesh.CreateFaceVertexIndicesAttr(faces.flatten().tolist())
        mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        mesh.CreateDisplayColorAttr([Gf.Vec3f(.55,.65,.6)])
    if item.kind!='region':
        proxy=UsdGeom.Cube.Define(stage,path+'/CollisionBounds');proxy.CreateSizeAttr(1.)
        proxy.AddScaleOp().Set(Gf.Vec3f(item.size.x,item.size.y,item.size.z))
        proxy.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
        UsdPhysics.CollisionAPI.Apply(proxy.GetPrim())
    if item.kind=='object':
        UsdPhysics.RigidBodyAPI.Apply(root.GetPrim())
        UsdPhysics.MassAPI.Apply(root.GetPrim()).CreateMassAttr(max(.001,item.mass_kg))
    return path
