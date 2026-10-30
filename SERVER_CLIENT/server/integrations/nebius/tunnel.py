"""Connect-only access to an Isaac worker on a Nebius GPU VM.

The operator creates, starts and stops the VM in the Nebius console; RoboDE never
changes billing state. It forwards the worker ports over SSH and checks the worker
before any simulation uses it. The guest idle watchdog still powers the VM off.
"""
import asyncio
import contextlib
import shutil
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx


class NebiusTunnel:
    def __init__(self, store):
        self.store = store
        self.process = None
        self.lock = asyncio.Lock()
        self.ready_timeout = 30
        self.state = {'status': 'disconnected', 'message': 'Start the Nebius GPU VM in the Nebius console, then connect.'}

    def configuration(self):
        from services.api.isaac import worker_configuration
        return worker_configuration(self.store)

    def enabled(self):
        return self.configuration().get('deployment') == 'nebius'

    def running(self):
        return self.process is not None and self.process.returncode is None

    @staticmethod
    def command(c):
        """SSH arguments; host and user are pattern-validated so neither can become an ssh option."""
        port = urlsplit(c['url']).port or 9100
        args = ['ssh', '-N', '-L', f'{port}:127.0.0.1:9100', '-L', '9200:127.0.0.1:9200',
                '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=30', '-o', 'BatchMode=yes',
                '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=15']
        if c.get('ssh_key_file'):
            if not Path(c['ssh_key_file']).is_file():
                raise ValueError('The configured SSH key file is missing on the RoboDE server')
            args += ['-i', c['ssh_key_file'], '-o', 'IdentitiesOnly=yes']
        return [*args, f"{c.get('nebius_ssh_user') or 'ubuntu'}@{c['nebius_host']}"]

    def snapshot(self):
        c = self.configuration()
        if c.get('deployment') != 'nebius':
            return {'configured': False, 'status': 'unconfigured', 'message': 'Isaac Sim is not configured to use a Nebius VM.'}
        if self.state['status'] == 'ready' and not self.running():
            self.state.update(status='disconnected', message='The SSH tunnel closed. Check that the Nebius VM is still running, then connect again.')
        return {'configured': True, 'host': c.get('nebius_host'), **self.state}

    async def connect(self):
        async with self.lock:
            c = self.configuration()
            if c.get('deployment') != 'nebius':
                raise ValueError('Choose Nebius VM as the Isaac Sim compute target first.')
            if not c.get('token'):
                raise ValueError('Set the Isaac worker token before connecting.')
            if not shutil.which('ssh'):
                raise ValueError('Install an OpenSSH client on the RoboDE server.')
            if not self.running():
                self.state.update(status='connecting', message=f"Opening SSH tunnel to {c['nebius_host']}…")
                self.process = await asyncio.create_subprocess_exec(*self.command(c), stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            deadline = time.monotonic() + self.ready_timeout
            last = 'Worker not reachable'
            async with httpx.AsyncClient(timeout=5) as client:
                while time.monotonic() < deadline:
                    if not self.running():
                        detail = (await self.process.stderr.read()).decode(errors='replace').strip()[-400:]
                        self.process = None
                        self.state.update(status='error', message='SSH could not connect. Check that the VM is running and the address, user and key are correct.' + (f' SSH said: {detail}' if detail else ''))
                        raise ValueError(self.state['message'])
                    try:
                        response = await client.get(c['url']+'/v1/health', headers={'Authorization': 'Bearer '+c['token']})
                        response.raise_for_status()
                        health = response.json()
                        from shared.models.worker import PROTOCOL
                        if health.get('protocol') != PROTOCOL or health.get('engine') != 'isaac_sim':
                            raise ValueError('The tunnel reached a service that is not a compatible Isaac Sim worker.')
                        self.state.update(status='ready', message=f"Connected to the Isaac worker on {c['nebius_host']}.",
                                          idle_guard_active=bool(health.get('idle_guard_active')))
                        return self.snapshot()
                    except (httpx.HTTPError, ValueError) as error:
                        last = str(error)
                        await asyncio.sleep(1)
            await self.close()
            self.state.update(status='error', message='SSH connected, but the Isaac worker did not answer: ' + last)
            raise ValueError(self.state['message'])

    async def ensure(self):
        """Called before a simulation uses Isaac; opens the tunnel if it is not already up."""
        if self.enabled() and not (self.running() and self.state['status'] == 'ready'):
            await self.connect()

    async def close(self):
        if self.running():
            self.process.terminate()
            with contextlib.suppress(ProcessLookupError):
                await asyncio.wait_for(self.process.wait(), 5)
        self.process = None
        if self.state['status'] in {'ready', 'connecting'}:
            self.state.update(status='disconnected', message='Disconnected. The Nebius VM keeps running until you stop it or its idle watchdog powers it off.')
