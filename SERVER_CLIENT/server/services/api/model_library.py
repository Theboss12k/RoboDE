"""Import declarative BOT model bundles. Executable plugins are never imported."""
import copy
import json
import shutil
import uuid
import yaml
from fastapi import APIRouter, Request
from shared.models.domain import Contract
from services.api.storage import safe_id
from services.validation.registry import MODEL_ROOT, load_model, load_instance, read_yaml, validate_positions
from services.planning.kinematics import supports_model

class ModelBundle(Contract):
    robot: dict
    actuators: dict
    kinematics: dict
    capabilities: dict
    initial_configuration: dict


def model_library_router(store,controller,controls):
    router = APIRouter(prefix='/api/registry')

    @router.get('/{model_id}/bundle')
    async def export(model_id:str):
        folder = store.model_folder(model_id)
        model = load_model(folder)
        initial = load_instance(folder/'instances/instance.yaml',model)['initial_configuration']
        robot = {k:v for k,v in model['robot'].items() if k not in {'schema_version','kinematics','actuators','capabilities','control_schemes','adapters'}}
        return dict(robot=robot,actuators=model['actuators'],kinematics=model['kinematics'],capabilities=model['capabilities'],initial_configuration=initial)

    def idle():
        if controller.leases or controls.sessions:
            raise ValueError('Stop runs and close controls before importing a reusable model')

    @router.post('/import',status_code=201)
    async def import_model(data:ModelBundle):
        idle()
        return register_bundle(store, data)

    from services.imports.urdf import URDFImports, Review, SuggestRequest, MAX_UPLOAD
    from fastapi.responses import FileResponse
    importer = URDFImports(store, controller.llm)

    @router.post('/urdf/drafts', status_code=201)
    async def urdf_upload(request: Request, filename: str, urdf_path: str = ''):
        idle()
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_UPLOAD:
                raise ValueError('URDF upload must be at most 32 MB')
        return importer.create(bytes(body), filename, urdf_path)

    @router.get('/urdf/drafts/{draft_id}')
    async def urdf_draft(draft_id: str):
        return importer.read(draft_id)

    @router.delete('/urdf/drafts/{draft_id}')
    async def urdf_delete(draft_id: str):
        shutil.rmtree(importer.folder(draft_id))
        return {'deleted': True}

    @router.post('/urdf/drafts/{draft_id}/suggest')
    async def urdf_suggest(draft_id: str, data: SuggestRequest):
        return await importer.suggest(draft_id, data)

    @router.post('/urdf/drafts/{draft_id}/validate')
    async def urdf_validate(draft_id: str, data: Review):
        bundle, provenance = importer.build(draft_id, data)
        model = register_bundle(store, ModelBundle.model_validate(bundle), activate=False)
        return {'bundle': bundle, 'provenance': provenance, 'planning_supported':model['planning_supported']}

    @router.post('/urdf/drafts/{draft_id}/commit', status_code=201)
    async def urdf_commit(draft_id: str, data: Review):
        idle()
        if not data.reviewed:
            raise ValueError('Review the extracted and configured values before saving the robot')
        bundle, provenance = importer.build(draft_id, data)
        return register_bundle(store, ModelBundle.model_validate(bundle), source=(importer.folder(draft_id), provenance))

    @router.get('/{model_id}/source')
    async def urdf_source(model_id: str):
        folder = store.model_folder(model_id) / 'source'
        if not (folder / 'import.json').exists():
            raise FileNotFoundError('This model has no retained URDF source')
        metadata = json.loads((folder / 'import.json').read_text())
        return FileResponse(folder / 'upload.bin', filename=metadata['filename'],
                            media_type='application/zip' if metadata['filename'].lower().endswith('.zip') else 'application/xml')

    return router


def register_bundle(store, data, *, activate=True, source=None):
    """Validate in staging, then atomically register; preview staging is outside the registry."""
    if len(data.model_dump_json()) > 2000000:
        raise ValueError('Robot definition is too large; maximum 2 MB')
    model_id = safe_id(str(data.robot.get('id','')))
    if activate and store.model_folder(model_id).exists():
        raise ValueError('Model ID already exists; choose a new ID before importing')
    root = store.runtime / ('imported_models' if activate else 'urdf_validation')
    root.mkdir(parents=True, exist_ok=True)
    temp = root / f'.import-{uuid.uuid4().hex}'
    temp.mkdir()
    def write(relative, value):
        path = temp / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value, sort_keys=False))
    try:
        robot = {**data.robot,'schema_version':'1.0','kinematics':'kinematics.yaml','actuators':'actuators.yaml','capabilities':'capabilities.yaml',
            'control_schemes':{key:f'control_schemes/{key}.yaml' for key in ('joint_position','trajectory_execution')},
            'adapters':{'mock':'adapters/mock.yaml','isaac_sim':'adapters/isaac_sim.yaml'}}
        write('robot.yaml', robot)
        for key in ('kinematics','actuators','capabilities'):
            write(f'{key}.yaml', getattr(data,key))
        template = load_model(MODEL_ROOT/'demo_arm')
        for key,value in template['control_schemes'].items():
            write(f'control_schemes/{key}.yaml',value)
        for key in ('mock','isaac_sim'):
            value = copy.deepcopy(template['adapters'][key])
            value['capabilities'] = data.capabilities.get('operations',[])
            if key == 'isaac_sim':
                value['available'] = False
                value['unavailable_reason'] = 'Import and validate a matching native USD cell and worker model before using Isaac Sim with this model'
            write(f'adapters/{key}.yaml', value)
        instance = {'schema_version':'1.0','instance':{'id':'template','name':robot.get('name','Template')},
            'robot_model':{'id':model_id,'version':robot.get('version','')},'base_pose':{'x':0,'y':0,'z':0,'yaw':0},
            'initial_configuration':data.initial_configuration}
        write('instances/instance.yaml', instance)
        if source:
            source_folder, provenance = source
            shutil.copytree(source_folder / 'package', temp / 'source/package')
            shutil.copyfile(source_folder / 'upload.bin', temp / 'source/upload.bin')
            from services.api.storage import atomic_json
            atomic_json(temp / 'source/import.json', provenance)
        model = load_model(temp)
        load_instance(temp / 'instances/instance.yaml', model)
        if activate:
            temp.rename(root / model_id)
        return {**model,'planning_supported':supports_model(model),'imported':True}
    finally:
        if temp.exists():shutil.rmtree(temp,ignore_errors=True)
