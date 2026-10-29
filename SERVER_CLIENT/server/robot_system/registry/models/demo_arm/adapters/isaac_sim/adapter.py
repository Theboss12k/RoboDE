"""HTTP transport for one Isaac Sim cell; every robot advances in one physics tick."""
import os
from datetime import datetime, timezone
import httpx
from shared.models.worker import PROTOCOL, WorkerObservation
from services.validation.registry import validate_positions


class WorkerUnavailable(ValueError):
    pass


class IsaacCell:
    def __init__(self, project_id, instances, models, objects, client=None, require_native=True, url=None, token=None, load_scene=False, room=None, transfer_positions=None):
        self.project_id, self.instances, self.models, self.objects = project_id, instances, models, objects
        self.load_scene=load_scene
        self.room=room
        self.transfer_positions=transfer_positions
        self.client = client or httpx.AsyncClient(base_url=(url or os.getenv('ISAAC_WORKER_URL','http://127.0.0.1:9100')).rstrip('/'),
            headers={'Authorization':f"Bearer {token if token is not None else os.getenv('ISAAC_WORKER_TOKEN','')}"}, timeout=10)
        self.require_native = require_native
        self.session_id = None
        self.sequence = 0
        self.metadata = {}
        self.latest = None
        self.asset_provider=None
        self.room_asset_path=None
        self.uploaded_assets=set()

    async def request(self, method, path, body=None):
        try:
            response = await self.client.request(method,path,json=body,timeout=180 if method=='POST' and (path=='/v1/sessions' or path.endswith('/recordings')) else 15)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            try:detail = error.response.json().get('detail','Worker rejected the request')
            except ValueError:detail='Worker rejected the request; check native worker logs'
            raise WorkerUnavailable(f'Isaac Sim worker: {detail}') from error
        except (httpx.HTTPError, ValueError) as error:
            if isinstance(error,WorkerUnavailable):
                raise
            raise WorkerUnavailable('Isaac Sim worker is unreachable or returned an invalid response. Check ISAAC_WORKER_URL, token and the GPU worker process.') from error

    async def connect(self):
        self.metadata = await self.request('GET','/v1/health')
        if self.metadata.get('protocol') != PROTOCOL:
            raise WorkerUnavailable('Isaac worker protocol version mismatch')
        if self.require_native and self.metadata.get('engine') != 'isaac_sim':
            raise WorkerUnavailable('This worker is a contract-test backend, not NVIDIA Isaac Sim')
        if self.transfer_positions is not None and not self.metadata.get('scene_loading'):
            raise WorkerUnavailable('Automatic scene transfer needs a managed Isaac worker. Launch it with --project-scene (or --asset-catalog for manufacturer USD models). A fixed scene cannot receive the project automatically.')
        if self.load_scene:
            self.uploaded_assets.clear()
            await self.upload_assets(self.objects)
            if self.room and self.room_asset_path:
                if not self.metadata.get('room_loading'):raise WorkerUnavailable('Enable ROBOT_IDE_ALLOW_ROOM_UPLOADS=1 on the managed worker to transfer this captured room')
                await self.upload_file('/v1/scene-assets/rooms/'+self.room['asset_id'],self.room_asset_path)
        robots = [{'instance':i,'model':self.models[i['instance']['id']]} for i in self.instances]
        body={'project_id':self.project_id,'robots':robots,'objects':[o.model_dump() for o in self.objects],'load_scene':self.load_scene,'room':self.room}
        if self.transfer_positions is not None:body['transfer_positions']=self.transfer_positions
        data = await self.request('POST','/v1/sessions',body)
        self.session_id = data['session_id']
        self.sequence = 0
        self.accept(data['observation'])
        # A lease renewal must observe, never replay the hand-off a second time.
        self.transfer_positions=None
        self.load_scene=False
        self.metadata=await self.request('GET','/v1/health')

    def accept(self, data):
        observation = WorkerObservation.model_validate(data)
        if observation.faults:
            raise WorkerUnavailable('; '.join(observation.faults))
        if observation.sequence < self.sequence:
            raise WorkerUnavailable('Out-of-order worker feedback')
        if set(observation.states) != set(self.models):
            raise WorkerUnavailable('Worker robot instance set does not match the project')
        if {o.id for o in observation.objects} != {o.id for o in self.objects}:
            raise WorkerUnavailable('Worker object IDs do not match the project scene')
        stamp = datetime.fromisoformat(observation.measured_at)
        if stamp.tzinfo is None or abs((datetime.now(timezone.utc)-stamp).total_seconds()) > 5:
            raise WorkerUnavailable('Worker feedback timestamp is stale or clocks are not synchronized')
        for rid,state in observation.states.items():
            if state.source != 'simulation' or not state.connected or state.instance_id != rid:
                raise WorkerUnavailable('Worker feedback is not connected simulated robot state')
            measured = datetime.fromisoformat(state.measured_at)
            if measured.tzinfo is None or abs((datetime.now(timezone.utc)-measured).total_seconds()) > 5:
                raise WorkerUnavailable(f'Stale joint feedback for {rid}')
            validate_positions(self.models[rid],state.positions)
        self.latest, self.sequence = observation, observation.sequence
        return observation

    async def observe(self):
        return self.accept(await self.request('GET',f'/v1/sessions/{self.session_id}/state'))

    async def advance(self, positions, dt):
        for rid,q in positions.items():
            validate_positions(self.models[rid],q)
        expected = self.sequence+1
        observation = self.accept(await self.request('POST',f'/v1/sessions/{self.session_id}/step',{'sequence':expected,'dt':dt,'positions':positions}))
        if observation.sequence != expected:
            raise WorkerUnavailable('Worker did not acknowledge the expected simulation tick')
        return observation

    async def reset(self, positions, objects):
        return self.accept(await self.request('POST',f'/v1/sessions/{self.session_id}/reset',{'positions':positions,'objects':[o.model_dump() for o in objects]}))

    async def sync_objects(self,objects):
        if not self.metadata.get('scene_editing'):raise ValueError('This worker uses a fixed scene; start with --project-scene or --asset-catalog to edit objects')
        await self.upload_assets(objects)
        previous=self.objects
        data=await self.request('PUT',f'/v1/sessions/{self.session_id}/objects',{'objects':[o.model_dump() for o in objects]})
        self.objects=objects
        try:
            observed=self.accept(data)
            self.metadata=await self.request('GET','/v1/health')
            return observed
        except BaseException:
            self.objects=previous
            raise

    async def reconfigure(self,instances,models,objects,positions,room=None):
        if not self.metadata.get('scene_loading'):
            raise ValueError('Robot placement requires a managed Isaac worker (--project-scene or --asset-catalog)')
        await self.upload_assets(objects)
        robots=[{'instance':i,'model':models[i['instance']['id']]} for i in instances]
        data=await self.request('PUT',f'/v1/sessions/{self.session_id}/scene',{
            'project_id':self.project_id,'robots':robots,'objects':[o.model_dump() for o in objects],'load_scene':True,'room':room if room is not None else self.room})
        self.instances,self.models,self.objects=instances,models,objects
        if room is not None:self.room=room
        self.accept(data)
        await self.reset(positions,objects)
        self.metadata=await self.request('GET','/v1/health')

    async def inventory(self):
        return await self.request('GET',f'/v1/sessions/{self.session_id}/assets')

    async def upload_file(self,url,path):
        try:
            with path.open('rb') as handle:
                response=await self.client.put(url,content=handle.read(),headers={'Content-Type':'application/octet-stream'},timeout=180)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            try:detail=error.response.json().get('detail','Asset upload rejected')
            except ValueError:detail='Asset upload rejected'
            raise WorkerUnavailable('Isaac Sim worker: '+str(detail)) from error
        except httpx.HTTPError as error:raise WorkerUnavailable('Scene asset transfer failed; check the worker connection') from error

    async def upload_assets(self,objects):
        meshes={o.mesh.asset_id:o.mesh for o in objects if o.mesh}
        if not meshes:return
        if not self.asset_provider or not self.metadata.get('asset_uploading'):
            raise WorkerUnavailable('Update the managed Isaac worker to automatically transfer imported GLB/glTF/OBJ/STL objects')
        for digest,mesh in meshes.items():
            if digest in self.uploaded_assets:continue
            record,path=self.asset_provider(digest)
            if record['format']!=mesh.format:raise ValueError('Imported mesh format differs from project metadata')
            await self.upload_file('/v1/scene-assets/meshes/'+digest+'?format='+mesh.format,path)
            self.uploaded_assets.add(digest)

    async def upload_room(self,path,digest):
        with path.open('rb') as handle:
            response=await self.client.put(f'/v1/sessions/{self.session_id}/room-assets/{digest}',content=handle.read(),headers={'Content-Type':'model/vnd.usdz+zip'},timeout=180)
        if not response.is_success:
            raise WorkerUnavailable('Isaac worker rejected the room upload. Enable room loading and update the worker.')
        return response.json()

    async def stop(self):
        return self.accept(await self.request('POST',f'/v1/sessions/{self.session_id}/stop',{}))

    async def disconnect(self):
        try:
            if self.session_id:
                await self.request('DELETE',f'/v1/sessions/{self.session_id}')
        finally:
            await self.client.aclose()


class IsaacRobot:
    def __init__(self,cell,rid,model):
        self.cell,self.rid,self.model = cell,rid,model
    async def get_state(self):
        return (await self.cell.observe()).states[self.rid]
    async def request_stop(self):
        await self.cell.stop()
    async def disconnect(self):
        pass  # Cell owner closes the shared transport exactly once.
