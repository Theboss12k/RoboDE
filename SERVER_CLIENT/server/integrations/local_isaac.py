"""Own an explicitly configured local Isaac worker; never install or launch on page load."""
import asyncio
import contextlib
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx
from shared.models.worker import PROTOCOL
from services.validation.registry import ROOT


def host_capabilities():
    return {
        'platform': sys.platform,
        'local_supported': sys.platform in {'linux', 'win32'},
        'gcloud_available': bool(shutil.which('gcloud')),
        'nvidia_tools_available': bool(shutil.which('nvidia-smi')),
        'supported_version': '6.2.x',
    }


class LocalIsaac:
    def __init__(self, store):
        self.store = store
        self.process = None
        self.task = None
        self.lock = asyncio.Lock()
        self.instance_id = None
        self.ready_timeout = 600
        self.poll_interval = 2
        self.state = {'status': 'stopped', 'message': 'Local Isaac Sim is stopped.'}

    def configuration(self):
        from services.api.isaac import worker_configuration
        return worker_configuration(self.store)

    def running(self):
        return self.process is not None and self.process.poll() is None

    def snapshot(self):
        if self.process is not None and self.process.poll() is not None and self.state['status'] in {'ready', 'starting'}:
            self.state = {'status': 'error', 'message': f'Isaac exited with code {self.process.returncode}. Check its log.'}
        return {**self.state, 'managed': self.running(), 'log_available': self.log_path.exists()}

    @property
    def log_path(self):
        return self.store.runtime / 'local_isaac/worker.log'

    def check(self):
        c = self.configuration()
        if c.get('deployment') != 'local':
            raise ValueError('Select and save This computer before starting local Isaac Sim.')
        if not host_capabilities()['local_supported']:
            raise ValueError('Isaac Sim cannot run natively on macOS. Choose GCP GPU VM or an existing Windows/Linux GPU worker.')
        launcher, source = Path(c.get('local_launcher', '')), Path(c.get('local_source', ''))
        if not launcher.is_absolute() or not launcher.is_file():
            raise ValueError('Choose the installed Isaac python.sh, python.bat, or Isaac-enabled Python executable.')
        if c['local_source_kind']!='automatic' and (not source.is_absolute() or not source.is_file()):
            raise ValueError('Choose an existing approved asset catalog or fixed scene manifest.')
        if sys.platform != 'win32' and not os.access(launcher, os.X_OK):
            raise ValueError('The Isaac Python launcher is not executable.')
        endpoint = urlsplit(c['url'])
        if endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1':
            raise ValueError('Managed local Isaac uses http://127.0.0.1:PORT, without a path.')
        port = endpoint.port or 80
        if not 1024 <= port <= 65535:
            raise ValueError('Use a local worker port between 1024 and 65535.')
        if len(c.get('token', '')) < 16:
            raise ValueError('Save a worker token before starting local Isaac.')
        return c, launcher, source, port

    def command(self, c, launcher, source, port):
        args = [str(launcher), '-m', 'simulation.isaac_sim.serve']
        args += ['--project-scene'] if c['local_source_kind']=='automatic' else [
            '--asset-catalog' if c['local_source_kind']=='catalog' else '--manifest',str(source)]
        args += ['--host', '127.0.0.1', '--port', str(port)]
        if c.get('local_gui', True):
            args.append('--gui')
        if sys.platform == 'win32' and launcher.suffix.lower() in {'.bat', '.cmd'}:
            # Batch files require cmd.exe. Quote every fixed/path argument and
            # reject expansion/metacharacters rather than constructing arbitrary shell commands.
            if any(any(ch in arg for ch in '\r\n\0"%!^&|<>') for arg in [*args, str(ROOT)]):
                raise ValueError('For the Windows batch launcher, use installation/catalog/checkout paths without shell metacharacters.')
            return [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/s', '/c',
                    '"' + ' '.join('"' + arg + '"' for arg in args) + '"']
        return args

    async def start(self):
        async with self.lock:
            if self.running():
                return self.snapshot()
            if self.task and not self.task.done():
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            c, launcher, source, port = self.check()
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1', port)) == 0:
                    raise ValueError('The local worker port is already in use. Stop that service or select Existing worker to attach to it.')
            command = self.command(c, launcher, source, port)
            self.instance_id = secrets.token_hex(16)
            env = {**os.environ, 'ISAAC_WORKER_TOKEN': c['token'],
                   'ROBOT_IDE_ISAAC_INSTANCE': self.instance_id,
                   'PYTHONPATH': os.pathsep.join(filter(None, [str(ROOT), os.environ.get('PYTHONPATH')]))}
            # Cloud watchdog/NuRec credentials belong to their own worker, not this child.
            for key in list(env):
                if key.startswith(('AI_', 'NUREC_', 'BUSINESS_')) or key in {'ROBOT_IDE_ACCESS_CODE', 'ROBOT_IDE_ACTIVITY_DIR', 'ROBOT_IDE_IDLE_SECONDS', 'ROBOT_IDE_GUARD_REQUIRED'}:
                    env.pop(key, None)
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.parent.chmod(0o700)
            with self.log_path.open('w') as log:
                self.log_path.chmod(0o600)
                try:
                    self.process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                                                    stderr=subprocess.STDOUT, start_new_session=sys.platform != 'win32')
                except OSError as error:
                    raise ValueError('Could not launch the selected Isaac Python environment: '+str(error)) from error
            self.state = {'status': 'starting', 'message': 'Opening local Isaac Sim. First launch and shader compilation can take several minutes.'}
            self.task = asyncio.create_task(self._wait_ready(c))
            return self.snapshot()

    async def _wait_ready(self, c):
        deadline = time.monotonic() + self.ready_timeout
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                while self.running() and time.monotonic() < deadline:
                    try:
                        r = await client.get(c['url'] + '/v1/health', headers={'Authorization': 'Bearer ' + c['token']})
                        r.raise_for_status()
                        h = r.json()
                        if h.get('instance_id') != self.instance_id:
                            raise ValueError('A different process answered on the local worker port.')
                        if h.get('protocol') != PROTOCOL or h.get('engine') != 'isaac_sim' or not str(h.get('simulator_version', '')).startswith('6.2.'):
                            raise ValueError('Local worker is not a compatible Isaac Sim 6.2 backend.')
                        self.state = {'status': 'ready', 'message': 'Local Isaac Sim is ready. Connect / read state to load the project.'}
                        return
                    except httpx.HTTPError:
                        await asyncio.sleep(self.poll_interval)
                raise ValueError('Isaac did not become ready. Check the log, GPU/driver compatibility, worker dependencies and approved USD assets.')
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._terminate()
            self.state = {'status': 'error', 'message': str(error)}

    async def ensure_running(self):
        await self.start()
        if self.task:
            await asyncio.shield(self.task)
        if self.snapshot()['status'] != 'ready':
            raise ValueError(self.state['message'])

    async def _terminate(self):
        if not self.running():
            return
        if sys.platform == 'win32':
            result = await asyncio.to_thread(subprocess.run, ['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                                            capture_output=True, timeout=20)
            if result.returncode and self.running():
                raise ValueError('Windows could not stop the owned Isaac process. Check its process and permissions.')
            await asyncio.to_thread(self.process.wait, timeout=5)
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                await asyncio.to_thread(self.process.wait, timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                await asyncio.to_thread(self.process.wait, timeout=5)

    async def stop(self):
        async with self.lock:
            if self.task and not self.task.done():
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            await self._terminate()
            self.state = {'status': 'stopped', 'message': 'Local Isaac process stopped. Robot stopped feedback is reported separately by the environment controls.'}
            return self.snapshot()

    async def close(self):
        await self.stop()

    def log_tail(self):
        if not self.log_path.exists():
            return ''
        with self.log_path.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 16000))
            text = stream.read().decode(errors='replace')
        token = self.configuration().get('token')
        return text.replace(token, '[redacted]') if token else text
