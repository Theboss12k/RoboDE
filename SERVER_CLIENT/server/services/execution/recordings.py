"""Project video history and local artifact caching, independent of robot ownership."""
import asyncio
import hashlib
import json
import re
from urllib.parse import quote
from services.api.storage import atomic_json
from shared.models.recording import ACTIVE_RECORDING, MAX_VIDEO_BYTES


class Recordings:
    def __init__(self, controller):
        self.controller = controller
        self.jobs = {}
        self.remotes = {}
        self.locks = {}
        self.pending = set()
        root = controller.storage.runtime/'recordings'
        for path in root.glob('*/*.json'):
            record = json.loads(path.read_text())
            if record['status'] in ACTIVE_RECORDING:
                record.update(status='interrupted', error='Runtime restarted; reconnect and recover worker recording history')
                atomic_json(path, record)

    def folder(self, project):
        if not (self.controller.storage.project_folder(project)/'project.yaml').is_file():
            raise ValueError('Project was not found')
        path = self.controller.storage.runtime/'recordings'/project
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path(self, project, rid):
        if not re.fullmatch('[a-f0-9]{32}', rid):
            raise ValueError('Invalid recording ID')
        return self.folder(project)/(rid+'.json')

    def save(self, project, record):
        if record.get('project_id') != project:
            raise ValueError('Worker returned a recording from another project')
        atomic_json(self.path(project, record['id']), record)
        return record

    def listing(self, project):
        records = [json.loads(p.read_text()) for p in self.folder(project).glob('*.json')]
        return sorted(records, key=lambda r:r['created_at'], reverse=True)

    def guard(self, project):
        if project in self.pending or any(r['status'] in ACTIVE_RECORDING for r in self.listing(project)):
            raise ValueError('Stop and finish the scene recording before disconnecting, resetting, or switching simulators')

    def remote(self, project):
        session = self.controller.sessions.get(project)
        if not session or not session.remote:
            raise ValueError('Connect this project to NVIDIA Isaac Sim before recording; recording does not boot the VM')
        return session.remote

    def capability(self, project):
        self.folder(project)
        session = self.controller.sessions.get(project)
        if not session or not session.remote:
            return {'available': False, 'reason': 'Connect this project to NVIDIA Isaac Sim to record its native camera. This panel does not start a VM.'}
        capability = session.remote.metadata.get('scene_recording')
        return capability or {'available': False, 'reason': 'Update the GPU worker to the recording-enabled RoboDE release and install its worker requirements.'}

    async def start(self, project, settings):
        async with self.locks.setdefault(project, asyncio.Lock()):
            self.guard(project)
            capability = self.capability(project)
            if not capability.get('available'):
                raise ValueError(capability['reason'])
            remote = self.remote(project)
            self.pending.add(project)
            try:
                record = await remote.request('POST', f'/v1/sessions/{remote.session_id}/recordings', settings)
                self.save(project, record)
            finally:
                self.pending.discard(project)
            self.remotes[record['id']] = remote
            self.jobs[record['id']] = asyncio.create_task(self.monitor(project, record['id']))
            return record

    async def stop(self, project, rid):
        record = self.get(project, rid)
        if record['status'] not in ACTIVE_RECORDING:
            return record
        remote = self.remote(project)
        result = await remote.request('POST', f'/v1/sessions/{remote.session_id}/recordings/{rid}/stop')
        return self.save(project, {**result, 'cached': False})

    def get(self, project, rid):
        path = self.path(project, rid)
        if not path.is_file():
            raise ValueError('Recording was not found in this project')
        return json.loads(path.read_text())

    async def refresh(self, project, rid):
        async with self.locks.setdefault(rid, asyncio.Lock()):
            previous = self.get(project, rid)
            if previous.get('cached') or previous['status'] in {'failed','interrupted'}:
                return previous
            remote = self.remotes.get(rid) or self.remote(project)
            result = await remote.request('GET', f'/v1/recordings/{rid}?project_id={quote(project, safe="")}')
            record = {**result, 'cached': False}
            if result['status'] == 'ready':
                path = self.folder(project)/(rid+'.mp4')
                temporary = path.with_suffix('.partial')
                try:
                    digest = hashlib.sha256()
                    size = 0
                    async with remote.client.stream('GET', f'/v1/recordings/{rid}/file', params={'project_id': project}, timeout=120) as response:
                        response.raise_for_status()
                        with temporary.open('wb') as handle:
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > MAX_VIDEO_BYTES:
                                    raise ValueError('Worker video exceeds the 256 MB download limit')
                                digest.update(chunk)
                                handle.write(chunk)
                    if size != result.get('byte_length') or size < 32:
                        raise ValueError('Worker returned an incomplete recording')
                    temporary.replace(path)
                    record.update(cached=True, sha256=digest.hexdigest(), byte_length=size)
                finally:
                    temporary.unlink(missing_ok=True)
            return self.save(project, record)

    async def monitor(self, project, rid):
        # Poll even when the Environment panel is closed. No provider start or
        # VM keepalive after the bounded native capture/export has completed.
        try:
            for _ in range(400):
                await asyncio.sleep(1)
                record = await self.refresh(project, rid)
                if record['status'] not in ACTIVE_RECORDING:
                    return
            raise ValueError('Recording exceeded its capture and export deadline')
        except asyncio.CancelledError:
            raise
        except Exception as error:
            record = self.get(project, rid)
            record.update(status='interrupted', error=str(error), cached=False)
            self.save(project, record)
        finally:
            self.remotes.pop(rid, None)

    async def recover(self, project):
        remote = self.remote(project)
        if not remote.metadata.get('scene_recording'):
            raise ValueError('This GPU worker does not support recording history')
        records = await remote.request('GET', f'/v1/sessions/{remote.session_id}/recordings')
        for record in records:
            previous = next((r for r in self.listing(project) if r['id']==record['id']), None)
            if previous and previous.get('cached'):
                continue
            self.save(project, record)
            self.remotes[record['id']] = remote
            if record['status'] in ACTIVE_RECORDING:
                if record['id'] not in self.jobs or self.jobs[record['id']].done():
                    self.jobs[record['id']] = asyncio.create_task(self.monitor(project, record['id']))
            else:
                await self.refresh(project, record['id'])
        return self.listing(project)

    async def close(self):
        for project in list(self.controller.sessions):
            for record in self.listing(project):
                if record['status'] in ACTIVE_RECORDING:
                    try:
                        await self.stop(project, record['id'])
                    except Exception:
                        pass
        running = [j for j in self.jobs.values() if not j.done()]
        if running:
            _, pending = await asyncio.wait(running, timeout=35)
            for job in pending:
                job.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        # Process exit must not leave a permanent scene-change guard.
        for project in list(self.controller.sessions):
            for record in self.listing(project):
                if record['status'] in ACTIVE_RECORDING:
                    self.save(project, {**record, 'status': 'interrupted', 'error': 'Runtime shut down before recording was exported; reconnect and recover worker history'})
