from fastapi import APIRouter
from fastapi.responses import FileResponse
from shared.models.recording import RecordingRequest


def recordings_router(controller):
    router = APIRouter(prefix='/api/projects/{project_id}/recordings', tags=['scene recordings'])
    service = controller.recordings

    @router.get('')
    async def listing(project_id:str):
        return service.listing(project_id)

    @router.get('/capabilities')
    async def capabilities(project_id:str):
        return service.capability(project_id)

    @router.post('', status_code=201)
    async def start(project_id:str, data:RecordingRequest):
        return await service.start(project_id, data.model_dump(mode='json'))

    @router.post('/recover')
    async def recover(project_id:str):
        return await service.recover(project_id)

    @router.get('/{record_id}')
    async def status(project_id:str, record_id:str):
        return service.get(project_id, record_id)

    @router.post('/{record_id}/stop')
    async def stop(project_id:str, record_id:str):
        return await service.stop(project_id, record_id)

    @router.get('/{record_id}/file')
    async def content(project_id:str, record_id:str):
        record = service.get(project_id, record_id)
        if not record.get('cached'):
            raise ValueError('Video is not cached yet; connect to its worker and recover recording history')
        return FileResponse(service.folder(project_id)/(record_id+'.mp4'), media_type='video/mp4',
            filename='RoboDE-scene-'+record_id+'.mp4', headers={'Cache-Control':'private, no-store', 'X-Content-SHA256':record['sha256']})

    return router
