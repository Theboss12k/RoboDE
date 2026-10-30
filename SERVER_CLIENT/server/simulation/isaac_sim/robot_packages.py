"""Content-pinned declarative robot transfer. No uploaded Python is accepted."""
import base64,hashlib,json,shutil,tempfile
from pathlib import Path
from services.api.storage import safe_id,fingerprint
from services.validation.registry import load_model,load_instance
from services.planning.kinematics import with_base
from services.adapters.bindings import enrich_model
ALLOWED={'.yaml','.yml','.json','.urdf','.stl','.obj','.dae','.glb','.gltf','.bin','.mtl','.png','.jpg','.jpeg'}

def package_model(store,model):
    folder=store.model_folder(model['robot']['id']);files={};total=0
    for p in sorted(folder.rglob('*')):
        if not p.is_file() or p.is_symlink() or p.suffix.lower() not in ALLOWED or '__pycache__' in p.parts:continue
        data=p.read_bytes();total+=len(data)
        if total>100*1024*1024:raise ValueError('Robot package exceeds 100 MB')
        files[str(p.relative_to(folder))]=base64.b64encode(data).decode()
    value={'files':files,'model_id':model['robot']['id']};value['hash']=fingerprint(value);return value

def receive_package(store,package):
    mid=safe_id(package['model_id'])
    if package['hash']!=fingerprint({k:package[k] for k in ('files','model_id')}):raise ValueError('Robot transfer checksum mismatch')
    files=package['files']
    if len(files)>2048:raise ValueError('Too many robot package files')
    root=store.runtime/'imported_models';root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.robot-transfer-',dir=root) as folder:
        folder=Path(folder).resolve();total=0
        for relative,encoded in files.items():
            p=(folder/relative).resolve()
            if not p.is_relative_to(folder) or p.suffix.lower() not in ALLOWED:raise ValueError('Robot packages contain only declarative models and geometry assets')
            data=base64.b64decode(encoded,validate=True);total+=len(data)
            if total>100*1024*1024:raise ValueError('Robot package exceeds 100 MB')
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        model=load_model(folder)
        if model['robot']['id']!=mid:raise ValueError('Transferred robot ID does not match its definition')
        load_instance(folder/'instances/instance.yaml',model)
        try:existing=load_model(store.model_folder(mid))
        except FileNotFoundError:existing=None
        if existing is not None:
            if existing!=model:raise ValueError('Worker robot model differs; import a new global model/version instead of overwriting it')
        else:shutil.copytree(folder,root/mid)
    return mid

def reviewed_model(store,instance,requested):
    raw=load_model(store.model_folder(instance['robot_model']['id']));binding=requested.get('binding')
    if binding:
        if not binding.get('published') or binding['model_hash']!=fingerprint(raw):raise ValueError('Transferred binding does not match the reviewed URDF')
        expected=fingerprint({k:binding[k] for k in ('definition','version','driver_hash','model_hash')})
        if binding['hash']!=expected or binding.get('reviewed_hash')!=expected:raise ValueError('Transferred robot mapping must be reviewed and content-pinned')
        raw=enrich_model(raw,binding)
    return with_base(raw,instance)
