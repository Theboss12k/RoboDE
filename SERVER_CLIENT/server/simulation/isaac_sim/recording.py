"""Observe native RGB renders without advancing physics; encode in a bounded worker thread."""
import contextlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

from services.api.storage import atomic_json
from shared.models.recording import RecordingRequest, ACTIVE_RECORDING, MAX_VIDEO_BYTES


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def encoder_binary():
    configured = os.getenv('ISAAC_FFMPEG_BINARY')
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_absolute() and path.is_file() and os.access(path, os.X_OK) else None
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


class NativeCamera:
    """Created/read/destroyed only on the Kit main thread. Render does not step physics."""
    def __init__(self, backend, settings, record_id):
        import omni.replicator.core as rep
        from pxr import Gf, UsdGeom
        cell = getattr(backend, 'cell', backend)
        if cell is None:
            raise ValueError('Load the project scene before recording')
        self.world, self.stage = cell.world, cell.world.stage
        self.path = '/RoboDERecording_' + record_id
        self.product, self.rgb = None, None
        try:
            from pxr import Usd
            with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
                camera = UsdGeom.Camera.Define(self.stage, self.path)
                # USD cameras look along -Z with +Y up; Gf's inverse view matrix
                # maps these camera axes into the project's Z-up world.
                matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*settings.position), Gf.Vec3d(*settings.look_at), Gf.Vec3d(0, 1, 0) if abs(settings.position[0]-settings.look_at[0])+abs(settings.position[1]-settings.look_at[1]) < .001 else Gf.Vec3d(0, 0, 1)).GetInverse()
                UsdGeom.Xformable(camera).AddTransformOp().Set(matrix)
                camera.CreateFocalLengthAttr().Set(20.)
                camera.GetClippingRangeAttr().Set(Gf.Vec2f(.01, 10000))
                width, height = map(int, settings.resolution.split('x'))
                self.product = rep.create.render_product(self.path, (width, height))
                self.rgb = rep.annotators.get('rgb')
                self.rgb.attach(self.product)
                for _ in range(3):
                    self.world.render()
        except BaseException:
            self.destroy()
            raise

    def resume(self, settings):
        from pxr import Gf, Usd, UsdGeom
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            up = Gf.Vec3d(0, 1, 0) if abs(settings.position[0]-settings.look_at[0])+abs(settings.position[1]-settings.look_at[1]) < .001 else Gf.Vec3d(0, 0, 1)
            matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*settings.position), Gf.Vec3d(*settings.look_at), up).GetInverse()
            UsdGeom.Xformable(self.stage.GetPrimAtPath(self.path)).GetOrderedXformOps()[0].Set(matrix)
        self.product.hydra_texture.set_updates_enabled(True)
        for _ in range(3):
            self.world.render()

    def frame(self):
        self.world.render()
        data = self.rgb.get_data()
        # Annotator RGB can have either three or four uint8 channels.
        if getattr(data, 'ndim', 0) != 3 or data.shape[2] not in (3, 4) or str(data.dtype) != 'uint8':
            raise ValueError('Isaac camera did not return a valid RGB frame')
        return data[:, :, :3].copy().tobytes()

    def close(self):
        # Isaac 6.2's annotator detach deletes graph prims and invalidates live
        # articulation views. Pause this scene-owned render product instead;
        # final destruction happens after robots stop, before scene unload.
        if self.product is not None:
            self.product.hydra_texture.set_updates_enabled(False)

    def destroy(self):
        from pxr import Usd
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            if self.rgb is not None:
                with contextlib.suppress(Exception):
                    self.rgb.detach()
            if self.product is not None:
                with contextlib.suppress(Exception):
                    self.product.destroy()
            self.stage.RemovePrim(self.path)


class SceneRecorder:
    """One capture at a time; no robot/control calls. Artifacts survive lease expiry."""
    def __init__(self, backend, root=None, camera_factory=NativeCamera, binary=None):
        self.backend = backend
        self.root = Path(root or os.getenv('ISAAC_RECORDINGS_DIR', '~/.local/share/robode/recordings')).expanduser()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.camera_factory = camera_factory
        self.binary = binary or encoder_binary()
        self.current = None
        self.source = None
        self.thread = None
        self.process = None
        self.finish_timer = None
        self.camera_cache = {}
        self.mutex = threading.RLock()
        for path in self.root.glob('*/metadata.json'):
            record = json.loads(path.read_text())
            if record['status'] in ACTIVE_RECORDING:
                record.update(status='interrupted', error='Worker restarted before the MP4 was finalized', finished_at=timestamp())
                atomic_json(path, record)
                (path.parent/'capture.partial.mp4').unlink(missing_ok=True)

    def capability(self):
        return {'available': bool(self.binary), 'max_duration_seconds': 300,
                'resolutions': ['640x360', '1280x720', '1920x1080'], 'fps': [5, 10, 15, 30],
                'reason': None if self.binary else 'Install requirements-worker.txt (imageio-ffmpeg) or configure ISAAC_FFMPEG_BINARY on the GPU host'}

    def _persist(self):
        atomic_json(self.root/self.current['id']/'metadata.json', self.current)

    def active(self):
        return self.current is not None and self.current['status'] in ACTIVE_RECORDING

    def guard(self):
        if self.active():
            raise ValueError('Stop and finish scene recording before replacing or resetting the simulator')

    def start(self, project, session, body):
        settings = RecordingRequest.model_validate(body)
        self.guard()
        if not self.binary:
            raise ValueError(self.capability()['reason'])
        records = list(self.root.glob('*/metadata.json'))
        if len(records) >= 100 or sum(p.stat().st_size for p in self.root.glob('*/*.mp4')) >= 1024**3:
            raise ValueError('Recording storage limit reached; archive or remove recordings on the GPU host')
        if shutil.disk_usage(self.root).free < MAX_VIDEO_BYTES * 2:
            raise ValueError('At least 512 MB of free disk space is required for recording')
        self._release_camera()
        record_id = uuid.uuid4().hex
        folder = self.root/record_id
        folder.mkdir(mode=0o700)
        self.current = {'id': record_id, 'project_id': project, 'session_id': session, 'status': 'recording',
                        'settings': settings.model_dump(mode='json'), 'created_at': timestamp(), 'frames': 0,
                        'duplicated_frames': 0, 'error': None, 'engine': self.backend.metadata.get('engine'),
                        'engine_version': self.backend.metadata.get('simulator_version'), 'timeline': 'wall_clock',
                        'physics_advanced_by_recording': False}
        self._persist()
        self.frames = queue.Queue(maxsize=4)
        self.ending = threading.Event()
        self.started = time.monotonic()
        self.deadline = self.started + settings.duration_seconds
        self.next_frame = self.started
        self.settings = settings
        self.last_frame = None
        try:
            if self.camera_factory is NativeCamera:
                cell = getattr(self.backend, 'cell', self.backend)
                key = (id(cell), settings.resolution)
                if key not in self.camera_cache:
                    self.camera_cache[key] = NativeCamera(self.backend, settings, record_id)
                else:
                    self.camera_cache[key].resume(settings)
                self.source = self.camera_cache[key]
            else:
                self.source = self.camera_factory(self.backend, settings, record_id)
            first = self.source.frame()
            self._validate_frame(first)
            self.started = time.monotonic()
            self.deadline = self.started + settings.duration_seconds
            self.next_frame = self.started
            # FFmpeg is separate from Kit and HTTP. Bounded queue prevents a
            # slow encoder or failed pipe from blocking robot execution.
            self.thread = threading.Thread(target=self._encode, name='scene-video-encoder', daemon=True)
            self.thread.start()
            self._enqueue(first)
            self.last_frame = first
            self.next_frame += 1/settings.fps
        except BaseException as error:
            self.current.update(status='failed', error=str(error), finished_at=timestamp())
            self._persist()
            self._release_camera()
            raise ValueError('Cannot start scene recording: '+str(error)) from error
        return self.get(project, record_id)

    def _validate_frame(self, data):
        width, height = map(int, self.settings.resolution.split('x'))
        if len(data) != width * height * 3:
            raise ValueError('Camera frame size does not match the selected recording resolution')

    def _enqueue(self, data):
        self._validate_frame(data)
        try:
            self.frames.put_nowait(data)
        except queue.Full as error:
            raise ValueError('Video encoder cannot keep up; try a lower resolution or frame rate') from error

    def tick(self):
        # Main thread only. This never calls world.step, reset, or advance.
        if not self.active():
            self._release_camera()
            return
        if self.current['status'] == 'finalizing':
            self._release_camera()
            return
        now = time.monotonic()
        if now >= self.deadline:
            self.stop('Duration limit reached')
            return
        if now < self.next_frame:
            return
        try:
            from integrations.gcp.activity import touch
            touch('isaac-recording')
            missed = int((now-self.next_frame)*self.settings.fps)
            # Repeated observed frames preserve wall-clock timing under render
            # load; never invent intermediate joint states or advance physics.
            if missed > 3:
                raise ValueError('Native rendering is too slow for this frame rate; lower the recording settings')
            for _ in range(missed):
                self._enqueue(self.last_frame)
                self.current['duplicated_frames'] += 1
            data = self.source.frame()
            self._enqueue(data)
            self.last_frame = data
            self.next_frame += (missed+1)/self.settings.fps
        except Exception as error:
            self.stop(error=str(error))

    def _release_camera(self):
        if self.source is not None:
            with contextlib.suppress(Exception):
                self.source.close()
            self.source = None

    def stop(self, reason='Stopped by user', error=None):
        if self.current is None:
            raise ValueError('No scene recording has been started')
        with self.mutex:
            if self.current['status'] == 'recording':
                self.current.update(status='finalizing', stop_reason=reason, error=error)
                self._persist()
                self.ending.set()
                # A stuck encoder pipe cannot retain a recording forever.
                self.finish_timer = threading.Timer(30, self._kill_encoder)
                self.finish_timer.daemon = True
                self.finish_timer.start()
        self._release_camera()
        return self.get(self.current['project_id'], self.current['id'])

    def _kill_encoder(self):
        process = self.process
        if process and process.poll() is None:
            with contextlib.suppress(OSError):
                process.kill()

    def _encode(self):
        record_id = self.current['id']
        folder = self.root/record_id
        partial = folder/'capture.partial.mp4'
        process = None
        failure = None
        try:
            # stderr goes to disk (not a pipe that can deadlock); never a shell.
            with (folder/'encoder.log').open('wb') as log:
                process = subprocess.Popen([self.binary, '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-video_size', self.settings.resolution,
                    '-framerate', str(self.settings.fps), '-i', 'pipe:0', '-an', '-c:v', 'libx264',
                    '-preset', 'veryfast', '-crf', '24', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                    '-fs', str(MAX_VIDEO_BYTES), str(partial)], stdin=subprocess.PIPE, stderr=log, stdout=subprocess.DEVNULL)
                self.process = process
                while not self.ending.is_set() or not self.frames.empty():
                    try:
                        frame = self.frames.get(timeout=.2)
                    except queue.Empty:
                        continue
                    process.stdin.write(frame)
                    self.current['frames'] += 1
                process.stdin.close()
                if process.wait(timeout=30) != 0:
                    raise ValueError('MP4 encoder failed; check GPU worker encoder.log')
                if self.current.get('error'):
                    raise ValueError(self.current['error'])
                if self.current['frames'] == 0 or not partial.is_file() or partial.stat().st_size >= MAX_VIDEO_BYTES:
                    raise ValueError('Recording is empty or reached the 256 MB size limit')
                partial.replace(folder/'scene.mp4')
        except Exception as error:
            failure = str(error)
        finally:
            if process and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if self.finish_timer:
                self.finish_timer.cancel()
            with self.mutex:
                self.current.update(status='failed' if failure else 'ready', error=failure,
                    finished_at=timestamp(), duration_seconds=self.current['frames']/self.settings.fps,
                    byte_length=(folder/'scene.mp4').stat().st_size if not failure else 0)
                self._persist()
            partial.unlink(missing_ok=True)

    def get(self, project, record_id):
        if not re.fullmatch('[a-f0-9]{32}', record_id):
            raise ValueError('Invalid recording ID')
        with self.mutex:
            if self.current and self.current['id'] == record_id:
                record = dict(self.current)
            else:
                path = self.root/record_id/'metadata.json'
                if not path.is_file():
                    raise ValueError('Recording was not found on this worker')
                record = json.loads(path.read_text())
        if record['project_id'] != project:
            raise ValueError('Recording belongs to another project')
        record.pop('session_id', None)
        return record

    def listing(self, project):
        return sorted([self.get(project, p.parent.name) for p in self.root.glob('*/metadata.json')
                       if json.loads(p.read_text())['project_id'] == project], key=lambda r: r['created_at'], reverse=True)

    def file(self, project, record_id):
        if self.get(project, record_id)['status'] != 'ready':
            raise ValueError('Recording is not ready for download')
        return self.root/record_id/'scene.mp4'

    def close(self):
        if self.active():
            self.stop('Worker shut down')
        if self.thread:
            self.thread.join(timeout=35)
        self.cleanup_cameras()

    def cleanup_cameras(self):
        self.guard()
        for camera in self.camera_cache.values():
            camera.destroy()
        self.camera_cache.clear()


class RecordingBackend:
    """Decorate a native backend, preserving its physics and ownership behavior."""
    def __init__(self, backend, **kwargs):
        self.backend = backend
        self.recorder = SceneRecorder(backend, **kwargs)
        if backend.metadata.get('scene_loading'):
            backend.before_scene_unload = self.recorder.cleanup_cameras

    def __getattr__(self, name):
        return getattr(self.backend, name)

    @property
    def metadata(self):
        return {**self.backend.metadata, 'scene_recording': self.recorder.capability()}

    def recording_start(self, project, session, body): return self.recorder.start(project, session, body)
    def recording_get(self, project, rid): return self.recorder.get(project, rid)
    def recording_list(self, project): return self.recorder.listing(project)
    def recording_file(self, project, rid): return self.recorder.file(project, rid)
    def recording_stop(self): return self.recorder.stop()
    def recording_end_session(self):
        if self.recorder.active(): self.recorder.stop('Worker session ended or expired')
    def load_scene(self, request):
        self.recorder.guard()
        return self.backend.load_scene(request)
    def reset(self, positions, objects):
        self.recorder.guard()
        return self.backend.reset(positions, objects)
