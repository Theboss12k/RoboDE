"""Build/start the optional local Linux robotics service. Never contacts GCP."""
import argparse
import json
import os
from pathlib import Path
import secrets
import time
import urllib.request
import urllib.error
import subprocess
from services.api.storage import atomic_json,Storage
from services.validation.registry import ROOT,REPOSITORY_ROOT


def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['build','start','stop','status']);p.add_argument('--image',default='robode-robotics:local');args=p.parse_args()
    if args.operation=='build':subprocess.run(['docker','build','-f','workers/robotics/Dockerfile','-t',args.image,'.'],cwd=REPOSITORY_ROOT,check=True);return
    if args.operation=='stop':subprocess.run(['docker','stop','robode-robotics'],check=True);return
    if args.operation=='status':subprocess.run(['docker','ps','--filter','name=robode-robotics','--format','{{.Names}} {{.Status}} {{.Ports}}'],check=True);return
    runtime=Storage().runtime/'connections';runtime.mkdir(parents=True,exist_ok=True)
    token=runtime/'motion.token'
    if not token.exists():token.write_text(secrets.token_urlsafe(40))
    token.chmod(0o600)
    env=runtime/'robotics-worker.env';env.write_text('ROBOT_DE_MOTION_TOKEN='+token.read_text().strip()+'\n');env.chmod(0o600)
    atomic_json(runtime/'motion.json',{'url':'http://127.0.0.1:9120','token_env':'ROBOT_DE_MOTION_TOKEN'})
    running=subprocess.run(['docker','ps','--filter','name=^/robode-robotics$','--format','{{.Names}}'],capture_output=True,text=True,check=True)
    if running.stdout.strip():print('Local robotics worker is already running.');return
    subprocess.run(['docker','run','-d','--rm','--init','--name','robode-robotics','--read-only','--tmpfs','/tmp:rw,size=1g','--cap-drop','ALL','--security-opt','no-new-privileges','--env-file',str(env),'-p','127.0.0.1:9120:9120',args.image],check=True,stdout=subprocess.DEVNULL)
    for attempt in range(60):
        request=urllib.request.Request('http://127.0.0.1:9120/v2/health',headers={'Authorization':'Bearer '+token.read_text().strip()})
        try:
            with urllib.request.urlopen(request,timeout=1) as response:ready=json.load(response)
            if ready.get('available'):break
        except (OSError,urllib.error.URLError):pass
        time.sleep(.5)
    else:raise RuntimeError('Container started but the robotics service is not ready; inspect docker logs robode-robotics')
    print('Local Linux robotics worker started on 127.0.0.1:9120. No cloud VM was started.')
if __name__=='__main__':main()
