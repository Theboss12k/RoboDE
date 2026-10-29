"""Project-local immutable 3D assets for the built-in simulator."""
import hashlib
import json
import re
import struct
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from services.api.storage import atomic_json

MAX_ASSET_BYTES = 25 * 1024 * 1024
FORMATS = {'glb', 'gltf', 'obj', 'stl'}


def asset_folder(store, project_id, asset_id):
    if not re.fullmatch(r'[a-f0-9]{64}', asset_id):
        raise ValueError('Invalid asset ID')
    return store.project_folder(project_id) / 'environment/assets' / asset_id


def asset_record(store, project_id, asset_id):
    folder = asset_folder(store, project_id, asset_id)
    record = json.loads((folder / 'metadata.json').read_text())
    if record['format'] not in FORMATS or record['id'] != asset_id or record['sha256'] != asset_id:
        raise ValueError('Invalid stored asset metadata')
    path = folder / ('model.' + record['format'])
    if not path.is_file():
        raise ValueError('Model asset file is missing')
    return record, path


def validate_asset_refs(store, project_id, objects):
    for item in objects:
        if item.mesh:
            record, _ = asset_record(store, project_id, item.mesh.asset_id)
            if record['format'] != item.mesh.format:
                raise ValueError('Object model format does not match its imported asset')


def validate_gltf(document):
    if not isinstance(document, dict) or document.get('asset', {}).get('version') != '2.0':
        raise ValueError('Import a glTF 2.0 model')
    if not document.get('meshes'):
        raise ValueError('The model has no mesh geometry')
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'uri' and (not isinstance(child, str) or not re.match(
                        r'^data:(?:application/(?:octet-stream|gltf-buffer)|image/(?:png|jpeg|webp));base64,', child)):
                    raise ValueError('Use a self-contained GLB or glTF with embedded buffers and textures; external files and URLs are not loaded')
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(document)
    if any(e in document.get('extensionsRequired', []) for e in ('KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_texture_basisu')):
        raise ValueError('Export an uncompressed model with PNG/JPEG/WebP textures before importing')


def validate_asset(data, extension):
    if not data or len(data) > MAX_ASSET_BYTES:
        raise ValueError('Model files must be nonempty and at most 25 MB')
    try:
        if extension == 'glb':
            if len(data) < 20:
                raise ValueError('Invalid GLB header')
            magic, version, length = struct.unpack_from('<4sII', data)
            chunk_length, chunk_type = struct.unpack_from('<II', data, 12)
            if magic != b'glTF' or version != 2 or length != len(data) or chunk_type != 0x4E4F534A or 20 + chunk_length > len(data):
                raise ValueError('Invalid GLB 2.0 file')
            validate_gltf(json.loads(data[20:20 + chunk_length]))
        elif extension == 'gltf':
            validate_gltf(json.loads(data))
        elif extension == 'obj':
            text = data.decode('utf-8-sig')
            if not re.search(r'^v\s', text, re.M) or not re.search(r'^f\s', text, re.M):
                raise ValueError('OBJ must contain vertices and faces')
        elif extension == 'stl':
            binary = len(data) >= 84 and 84 + struct.unpack_from('<I', data, 80)[0] * 50 == len(data)
            if not binary:
                text = data.decode('utf-8-sig')
                if not text.lstrip().startswith('solid') or 'facet normal' not in text or 'vertex' not in text or 'endsolid' not in text:
                    raise ValueError('Invalid ASCII or binary STL file')
        else:
            raise ValueError('Supported formats: GLB, embedded glTF, OBJ and STL')
    except (UnicodeDecodeError, json.JSONDecodeError, struct.error, TypeError, AttributeError, RecursionError) as error:
        raise ValueError('Invalid model file; export GLB, embedded glTF, OBJ or STL') from error


def assets_router(store, controller):
    router = APIRouter(prefix='/api/projects/{project_id}/assets')

    @router.post('', status_code=201)
    async def upload(project_id: str, request: Request, filename: str):
        controller.ensure_idle(project_id)
        project = store.load_project(project_id)[0]
        if project.get('simulation', {}).get('adapter', 'mock') != 'mock':
            session=controller.sessions.get(project_id)
            if not session or not session.remote or not session.remote.metadata.get('asset_uploading'):
                raise ValueError('Connect an updated managed Isaac worker to import 3D objects')
        name = re.split(r'[/\\]', filename)[-1].strip()[:180]
        extension = Path(name).suffix.lower().removeprefix('.')
        if extension not in FORMATS:
            raise ValueError('Supported formats: GLB, embedded glTF, OBJ and STL')
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_ASSET_BYTES:
                raise HTTPException(413, 'Model file exceeds the 25 MB limit')
            data.extend(chunk)
        validate_asset(data, extension)
        controller.ensure_idle(project_id)
        digest = hashlib.sha256(data).hexdigest()
        folder = asset_folder(store, project_id, digest)
        if (folder / 'metadata.json').exists():
            return asset_record(store, project_id, digest)[0]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ('model.' + extension)
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(data)
        temporary.replace(path)
        record = {'id':digest, 'filename':name, 'format':extension, 'sha256':digest, 'byte_length':len(data)}
        atomic_json(folder / 'metadata.json', record)
        return record

    @router.get('/{asset_id}')
    async def content(project_id: str, asset_id: str):
        # Existing historical revisions can still read their imported assets.
        record, path = asset_record(store, project_id, asset_id)
        return FileResponse(path, media_type='application/octet-stream', headers={
            'Content-Disposition': 'inline', 'X-Asset-SHA256':record['sha256']})

    return router
