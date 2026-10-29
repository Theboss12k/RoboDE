"""Local process/transport contracts use a stub, never native GPU physics."""
import asyncio
import os
from pathlib import Path, PureWindowsPath
import socket
import sys
from types import SimpleNamespace

import pytest
from integrations.local_isaac import LocalIsaac
from services.api.storage import atomic_json


@pytest.fixture
def local_worker(store, tmp_path, monkeypatch):
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0));port=s.getsockname()[1]
    source=tmp_path/'catalog.yaml';source.write_text('robots: {}')
    atomic_json(store.runtime/'connections/isaac.json', {
        'deployment':'local','url':f'http://127.0.0.1:{port}','token':'private-local-test-token',
        'local_launcher':sys.executable,'local_source':str(source),'local_source_kind':'catalog','local_gui':True,
    })
    script=tmp_path/'stub.py'
    script.write_text('''import http.server,json,os,sys
from shared.models.worker import PROTOCOL
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  if self.headers.get('Authorization')!='Bearer '+os.environ['ISAAC_WORKER_TOKEN']:
   self.send_response(401);self.end_headers();return
  self.send_response(200);self.end_headers()
  self.wfile.write(json.dumps({'protocol':PROTOCOL,'engine':'isaac_sim','simulator_version':'6.2.x',
   'instance_id':os.getenv('STUB_WRONG_ID',os.environ['ROBOT_IDE_ISAAC_INSTANCE'])}).encode())
print(os.environ['ISAAC_WORKER_TOKEN'],flush=True)
assert 'ROBOT_IDE_ACCESS_CODE' not in os.environ
assert 'NUREC_WORKER_TOKEN' not in os.environ
http.server.HTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()
''')
    monkeypatch.setattr('integrations.local_isaac.host_capabilities', lambda:{'local_supported':True})
    manager=LocalIsaac(store);manager.poll_interval=.02;manager.ready_timeout=3
    monkeypatch.setattr(manager,'command',lambda *args:[sys.executable,str(script),str(port)])
    return manager,port


def test_local_worker_is_owned_reusable_redacted_and_stopped(local_worker, monkeypatch):
    manager,port=local_worker
    monkeypatch.setenv('ROBOT_IDE_ACCESS_CODE','team-code-secret');monkeypatch.setenv('NUREC_WORKER_TOKEN','other-secret')
    async def run():
        try:
            assert (await manager.start())['status']=='starting'
            child=manager.process
            await manager.task
            assert manager.snapshot()['status']=='ready',manager.snapshot()
            assert (await manager.start())['status']=='ready'
            assert manager.process is child
            assert 'private-local-test-token' not in manager.log_tail()
            assert '[redacted]' in manager.log_tail()
            other=LocalIsaac(manager.store)
            with pytest.raises(ValueError,match='already in use'):await other.start()
            await manager.stop()
            assert not manager.running() and child.poll() is not None
        finally:await manager.close()
    asyncio.run(run())


def test_foreign_health_response_cannot_mark_local_process_ready(local_worker,monkeypatch):
    manager,_=local_worker;monkeypatch.setenv('STUB_WRONG_ID','different-worker')
    async def run():
        try:
            await manager.start();await manager.task
            assert manager.snapshot()['status']=='error'
            assert 'different process' in manager.state['message']
            assert not manager.running()
        finally:await manager.close()
    asyncio.run(run())


def test_startup_timeout_and_cancellation_reap_owned_child(local_worker,monkeypatch):
    manager,_=local_worker;manager.ready_timeout=.02
    monkeypatch.setattr(manager,'command',lambda *args:[sys.executable,'-c','import time;time.sleep(60)'])
    async def run():
        await manager.start();await manager.task
        assert manager.snapshot()['status']=='error' and not manager.running()
        manager.ready_timeout=60
        await manager.start();child=manager.process
        await manager.close()
        assert child.poll() is not None and manager.task.done()
    asyncio.run(run())


def test_mac_local_launch_rejected_before_spawning(store,monkeypatch):
    atomic_json(store.runtime/'connections/isaac.json',{'deployment':'local'})
    monkeypatch.setattr('integrations.local_isaac.host_capabilities',lambda:{'local_supported':False})
    manager=LocalIsaac(store)
    with pytest.raises(ValueError,match='macOS'):manager.check()
    assert manager.process is None


def test_automatic_project_scene_needs_no_scene_file(local_worker):
    import json
    manager,_=local_worker
    path=manager.store.runtime/'connections/isaac.json'
    c=json.loads(path.read_text());c.update(local_source_kind='automatic',local_source='')
    atomic_json(path,c)
    checked,launcher,source,port=manager.check()
    # Call the class method, bypassing this fixture's process stub.
    command=LocalIsaac.command(manager,checked,launcher,source,port)
    assert '--project-scene' in command and '--asset-catalog' not in command and '--manifest' not in command


def test_windows_batch_launcher_quotes_spaces_and_rejects_shell_expansion(store,monkeypatch):
    monkeypatch.setattr('integrations.local_isaac.sys',SimpleNamespace(platform='win32'))
    manager=LocalIsaac(store)
    c={'local_source_kind':'catalog','local_gui':True}
    command=manager.command(c,PureWindowsPath('C:/Isaac Sim/python.bat'),PureWindowsPath('C:/My assets/catalog.yaml'),9100)
    assert command[1:4]==['/d','/s','/c']
    assert '"C:\\Isaac Sim\\python.bat"' in command[-1]
    assert '"C:\\My assets\\catalog.yaml"' in command[-1]
    with pytest.raises(ValueError,match='metacharacters'):
        manager.command(c,PureWindowsPath('C:/Isaac/python.bat'),PureWindowsPath('C:/%PATH%/catalog.yaml'),9100)
