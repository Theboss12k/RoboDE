"""Protected temporary HTTPS access for phones. GPU services are never started here.
python -m scripts.phone_access [start|status|stop]
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from services.validation.registry import ROOT,REPOSITORY_ROOT

DIRECTORY=ROOT/'robot_system/runtime/phone'
STATE=DIRECTORY/'access.json'


def load():return json.loads(STATE.read_text()) if STATE.exists() else {}
def save(data):
    DIRECTORY.mkdir(parents=True,exist_ok=True);DIRECTORY.chmod(0o700)
    temporary=STATE.with_suffix('.tmp');temporary.write_text(json.dumps(data,indent=2));temporary.chmod(0o600);temporary.replace(STATE)
def running(pid):
    if not pid:return False
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False

def stop():
    data=load()
    for key,signature in [('tunnel_pid','cloudflared'),('gateway_pid','BUSINESS_APP.server'),('runtime_pid','services.api.main:app')]:
        pid=data.get(key)
        if running(pid):
            command=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout
            if signature in command:os.kill(pid,signal.SIGTERM)
    data.update(url=None,tunnel_pid=None,gateway_pid=None,runtime_pid=None);save(data)


def start():
    data=load()
    if data.get('url') and running(data.get('tunnel_pid')) and running(data.get('gateway_pid')):
        print(json.dumps({'url':data['url'],'access_code':data['access_code'],'note':'Keep this server awake. Stop access with npm run business:phone:stop.'}));return
    stop();data=load();data['access_code']=data.get('access_code') or secrets.token_urlsafe(18);save(data)
    if not (REPOSITORY_ROOT/'BUSINESS_APP/dist/index.html').exists():raise SystemExit('Run npm run business:build first.')
    binary=shutil.which('cloudflared') or str(ROOT/'robot_system/runtime/tools/cloudflared')
    if not Path(binary).is_file():raise SystemExit('Install cloudflared from https://developers.cloudflare.com/tunnel/downloads/ first.')
    def spawn(args,name,**kwargs):
        with (DIRECTORY/(name+'.log')).open('w') as log:return subprocess.Popen(args,cwd=REPOSITORY_ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,**kwargs).pid
    try:
        urllib.request.urlopen('http://127.0.0.1:8765/api/business/projects',timeout=3)
    except Exception:
        # Never substitute an unknown service already occupying the API port.
        try:urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=2)
        except Exception:pass
        else:raise SystemExit('An older Robot IDE runtime is running. Restart it to load the business API, then retry.')
        data['runtime_pid']=spawn([sys.executable,'-m','uvicorn','services.api.main:app','--host','127.0.0.1','--port','8765'],'runtime');save(data)
        for _ in range(60):
            try:urllib.request.urlopen('http://127.0.0.1:8765/api/business/projects',timeout=2);break
            except Exception:time.sleep(.5)
        else:stop();raise SystemExit('Runtime did not start. Inspect SERVER_CLIENT/server/robot_system/runtime/phone/runtime.log.')
    env={**os.environ,'BUSINESS_ACCESS_CODE':data['access_code']}
    data['gateway_pid']=spawn([sys.executable,'-m','BUSINESS_APP.server','--host','127.0.0.1','--port','8080'],'gateway',env=env);save(data)
    for _ in range(30):
        try:urllib.request.urlopen('http://127.0.0.1:8080/login',timeout=2);break
        except Exception:time.sleep(.3)
    else:stop();raise SystemExit('Gateway failed to start. Inspect its log.')
    data['tunnel_pid']=spawn([binary,'tunnel','--url','http://127.0.0.1:8080','--no-autoupdate','--protocol','http2'],'tunnel');save(data)
    for _ in range(120):
        match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',(DIRECTORY/'tunnel.log').read_text())
        if match:
            data['url']=match.group(0);save(data)
            print(json.dumps({'url':data['url'],'access_code':data['access_code'],'note':'Temporary HTTPS link. Keep this server awake and Robot IDE running. Room photos are saved on this server; reconstruction requires a configured GPU worker.'}));return
        if not running(data['tunnel_pid']):break
        time.sleep(.5)
    stop();raise SystemExit('HTTPS tunnel did not start. Inspect SERVER_CLIENT/server/robot_system/runtime/phone/tunnel.log.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',nargs='?',choices=['start','status','stop'],default='start');args=parser.parse_args()
    if args.command=='start':start()
    elif args.command=='stop':stop();print('Phone access stopped.')
    else:
        data=load();print(json.dumps({'url':data.get('url'),'running':running(data.get('tunnel_pid')) and running(data.get('gateway_pid')),'access_code':data.get('access_code')}))
