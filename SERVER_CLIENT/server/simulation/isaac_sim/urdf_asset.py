"""Isaac 6.x documented importer, called only inside the native GPU worker."""
import hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path

def convert(model,model_folder,folder):
    import omni.kit.app
    from pxr import Usd,UsdPhysics,Tf
    manager=omni.kit.app.get_app().get_extension_manager()
    manager.set_extension_enabled_immediate('isaacsim.asset.importer.urdf',True)
    try:from isaacsim.asset.importer.urdf import URDFImporter,URDFImporterConfig
    except ImportError as error:raise ValueError('Install the documented Isaac URDFImporter API before transferring this robot') from error
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);metadata=model['source_import'];source=Path(model_folder)/'source/package';urdf=(source/metadata['urdf_path']).resolve()
    if not urdf.is_relative_to(source.resolve()) or hashlib.sha256(urdf.read_bytes()).hexdigest()!=metadata['sha256']:raise ValueError('URDF source changed after review')
    root=ET.fromstring(urdf.read_bytes());meshes={m['uri']:m for m in metadata.get('meshes',[])}
    for node in root.findall('.//mesh'):
        item=meshes.get(node.get('filename'))
        if not item or item['status']!='retained':raise ValueError('Transfer every URDF mesh before native import')
        mesh=(source/item['path']).resolve()
        if not mesh.is_relative_to(source.resolve()) or hashlib.sha256(mesh.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('URDF mesh checksum mismatch')
        node.set('filename',str(mesh))
    sanitized=folder/'robot.urdf';sanitized.write_bytes(ET.tostring(root))
    moving=model.get('mobility',{}).get('classification','STATIONARY')!='STATIONARY'
    wheels={model.get('mobility',{}).get(k) for k in ('left_wheel','right_wheel')}
    targets={name:'velocity' if name in wheels else 'position' for name in model['actuators']['actuators']}
    config=URDFImporterConfig(urdf_path=str(sanitized),usd_path=str(folder/'usd'),merge_fixed_joints=False,merge_mesh=False,collision_from_visuals=False,allow_self_collision=True,fix_base=not moving,joint_drive_type='force',joint_target_type=targets)
    output=Path(URDFImporter(config).import_urdf()).resolve()
    if not output.is_relative_to(folder.resolve()) or not output.is_file():raise ValueError('Native URDF import produced no contained USD asset')
    stage=Usd.Stage.Open(str(output));default=stage.GetDefaultPrim()
    if not default:raise ValueError('Imported robot has no default USD prim')
    roots=[p for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
    if len(roots)!=1:raise ValueError('Imported URDF must have one articulation root')
    relative=str(roots[0].GetPath().MakeRelativePath(default.GetPath()))
    if relative=='.':relative=''
    joints={name:Tf.MakeValidIdentifier(name) for name in model['actuators']['actuators']}
    return {'usd':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'joints':joints,'articulation_path':relative,'provenance':'reviewed_urdf_native_import','native_gpu_validation':'required_at_connect'}
