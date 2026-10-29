"""On-demand lifecycle for one operator-configured GCP GPU VM. No provisioning.
The provider runtime limit is verified before boot; the independent guest guard
must report healthy before the VM becomes available to application callers.
"""
import asyncio
import contextlib
import json
import shutil
import time
import httpx


class GpuLifecycle:
    def __init__(self,store,runner=None):
        self.store=store;self.runner=runner or self._run;self.task=None;self.tunnel=None
        self.state={'configured':False,'status':'unconfigured','message':'Configure a GCP project, GPU VM and shutdown guard in Robot IDE.'}
        self.lock=asyncio.Lock();self.ready_timeout=300;self.poll_interval=3

    def configuration(self):
        from services.api.isaac import worker_configuration
        return worker_configuration(self.store)

    def enabled(self):return bool(self.configuration().get('on_demand',False))

    async def _run(self,args):
        if not shutil.which('gcloud'):raise ValueError('Install Google Cloud CLI and run gcloud auth login on the workspace host.')
        proc=await asyncio.create_subprocess_exec('gcloud',*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:stdout,stderr=await asyncio.wait_for(proc.communicate(),180)
        except BaseException:
            with contextlib.suppress(ProcessLookupError):proc.kill()
            await proc.wait();raise
        if proc.returncode:raise ValueError('Google Cloud command failed: '+stderr.decode(errors='replace')[-1500:])
        return json.loads(stdout) if stdout.strip() else {}

    def flags(self,c):
        if not all(c.get(k) for k in ('gcp_project','gcp_zone','gcp_instance')):raise ValueError('Set GCP project ID, zone and VM name before enabling on-demand GPU.')
        return ['--project='+c['gcp_project'],'--zone='+c['gcp_zone'],'--quiet','--format=json']

    async def describe(self,c):return await self.runner(['compute','instances','describe',c['gcp_instance'],*self.flags(c)])

    async def snapshot(self,refresh=False):
        c=self.configuration()
        if not c.get('on_demand'):return {**self.state,'configured':False,'status':'unconfigured'}
        if refresh and not (self.task and not self.task.done()):
            try:
                vm=await self.describe(c)
                if vm['status']!='RUNNING' or self.state['status']!='ready':self.state.update(configured=True,status=vm['status'].lower(),message='GPU VM '+vm['status'].lower())
            except ValueError as e:self.state.update(configured=True,status='error',message=str(e))
        return {**self.state,'configured':True,'status':'unknown' if self.state['status']=='unconfigured' else self.state['status'],'idle_minutes':c.get('idle_minutes',10),'max_session_minutes':c.get('max_session_minutes',120)}

    def request_start(self):
        if not self.enabled():raise ValueError('On-demand GPU is not configured. Configure it in Robot IDE first.')
        if not self.task or self.task.done():
            self.state.update(configured=True,status='starting',message='Starting GPU and checking shutdown safeguards…')
            self.task=asyncio.create_task(self._start())
        return {'configured':True,'status':'starting','message':'Starting GPU and checking its shutdown safeguards. This can take several minutes.'}

    async def ensure_running(self):
        if not self.enabled():return
        self.request_start();await asyncio.shield(self.task)
        if self.state['status']!='ready':raise ValueError(self.state['message'])

    async def _start(self):
        async with self.lock:
            c=self.configuration();flags=self.flags(c);booted=False
            self.state.update(configured=True,status='starting',message='Checking GPU VM and provider runtime limit…')
            try:
                vm=await self.describe(c)
                limit=c.get('max_session_minutes',120)*60
                if vm['status']=='TERMINATED':
                    await self.runner(['compute','instances','set-scheduling',c['gcp_instance'],*flags,'--max-run-duration='+str(limit)+'s','--instance-termination-action=STOP','--no-restart-on-failure'])
                    vm=await self.describe(c)
                scheduling=vm.get('scheduling',{})
                seconds=int(scheduling.get('maxRunDuration',{}).get('seconds',0))
                if scheduling.get('instanceTerminationAction')!='STOP' or not 30<=seconds<=limit or scheduling.get('automaticRestart',True):
                    raise ValueError('VM lacks the required STOP runtime limit or has automatic restart enabled. Stop it and save the shutdown configuration first.')
                if vm['status']=='TERMINATED':
                    booted=True
                    await self.runner(['compute','instances','start',c['gcp_instance'],*flags])
                elif vm['status']!='RUNNING':raise ValueError('VM is '+vm['status']+'. Wait for that transition before starting it again.')
                if self.runner==self._run:await self._open_tunnel(c)
                self.state['message']='Waiting for GPU worker and independent idle watchdog…'
                async with httpx.AsyncClient(timeout=5) as client:
                    deadline=time.monotonic()+self.ready_timeout;last='Worker not reachable'
                    while time.monotonic()<deadline:
                        try:
                            # The provider may report RUNNING before SSH is
                            # accepting connections. Retry an exited forwarder
                            # within the existing bounded startup window.
                            if self.runner==self._run and (self.tunnel is None or self.tunnel.returncode is not None):
                                await self._open_tunnel(c)
                            r=await client.get(c['url']+'/v1/health',headers={'Authorization':'Bearer '+c['token']});r.raise_for_status();health=r.json()
                            if health.get('protocol')!='robot-ide.isaac.v1':
                                from shared.models.worker import PROTOCOL
                                if health.get('protocol')!=PROTOCOL:raise ValueError('The tunnel is not connected to a compatible Isaac worker.')
                            if health.get('idle_timeout_seconds')!=c.get('idle_minutes',10)*60:raise ValueError('VM idle timeout differs from the saved settings. Update the guest watchdog service first.')
                            if not health.get('idle_guard_active'):raise ValueError('Independent GPU idle watchdog is not running. Install/start it on the VM before use.')
                            apps=health.get('cloud_apps',{})
                            if health.get('cloud_apps_installed'):
                                apps={'ide':'http://127.0.0.1:18083','business':'http://127.0.0.1:18084',**apps}
                            self.state.update(status='ready',message='GPU ready. Stops after inactivity; provider enforces the maximum session duration.',cloud_apps=apps);return
                        except (httpx.HTTPError,ValueError) as error:
                            last=str(error)
                            await asyncio.sleep(self.poll_interval)
                    raise ValueError('GPU worker did not become ready: '+last)
            except Exception as error:
                if booted:
                    try:await self.runner(['compute','instances','stop',c['gcp_instance'],*flags])
                    except Exception as stop_error:
                        self.state.update(status='error',message=f'{error} Automatic stop failed: {stop_error}. Stop the VM in Google Cloud Console.');return
                self.state.update(status='error',message=str(error))

    async def _open_tunnel(self,c):
        from urllib.parse import urlsplit
        p=urlsplit(c['url'])
        if p.hostname not in {'127.0.0.1','localhost'}:return
        if self.tunnel and self.tunnel.returncode is None:return
        port=p.port or 9100
        args=['gcloud','compute','ssh',c['gcp_instance'],'--project='+c['gcp_project'],'--zone='+c['gcp_zone'],'--quiet']
        if c.get('ssh_key_file'):
            from pathlib import Path
            if not Path(c['ssh_key_file']).is_file():raise ValueError('Configured IDE SSH key is missing on this server')
            args+=['--ssh-key-file='+c['ssh_key_file'],'--ssh-key-expire-after=2h']
        if c.get('use_iap',True):args+=['--tunnel-through-iap']
        # Separate SSH lifetime; service logs contain no access tokens.
        self.tunnel=await asyncio.create_subprocess_exec(*args,'--','-N','-L',f'{port}:127.0.0.1:9100','-L','9200:127.0.0.1:9200','-L','18083:127.0.0.1:8083','-L','18084:127.0.0.1:8084','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-o','BatchMode=yes',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)

    async def stop(self):
        if self.task and not self.task.done():raise ValueError('GPU startup is still in progress.')
        async with self.lock:
            c=self.configuration();await self.runner(['compute','instances','stop',c['gcp_instance'],*self.flags(c)])
            self.state.update(status='terminated',message='GPU VM stopped. Retained disk storage may still incur charges.')
            await self.close();return await self.snapshot()

    async def close(self):
        if self.task and not self.task.done():
            # A cancelled startup must finish its failure/stop handling.
            await asyncio.shield(self.task)
        if self.tunnel and self.tunnel.returncode is None:
            self.tunnel.terminate();await self.tunnel.wait()
