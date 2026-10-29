"""Serve the built React IDE, with a shared-team login and server-side API proxy."""
import argparse
import json
import os
from pathlib import Path
import secrets
from web.gateway import create_gateway
from services.validation.registry import ROOT
from services.api.storage import atomic_json


def access_code():
    configured=os.getenv('ROBOT_IDE_ACCESS_CODE')
    if configured:
        if len(configured)<12:raise ValueError('ROBOT_IDE_ACCESS_CODE must have at least 12 characters')
        return configured
    directory=ROOT/'robot_system/runtime/server';directory.mkdir(parents=True,exist_ok=True);directory.chmod(0o700)
    path=directory/'access.json'
    if not path.exists():
        atomic_json(path,{'access_code':secrets.token_urlsafe(24)});path.chmod(0o600)
    return json.loads(path.read_text())['access_code']

if __name__=='__main__':
    import uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--host',default=os.getenv('ROBOT_IDE_HOST','0.0.0.0'));parser.add_argument('--port',type=int,default=int(os.getenv('ROBOT_IDE_PORT','8081')));args=parser.parse_args()
    code=access_code()
    print(f'RoboDE browser URL: http://localhost:{args.port}\nShared team access code: {code}',flush=True)
    uvicorn.run(create_gateway(upstream=os.getenv('ROBOT_IDE_UPSTREAM','http://127.0.0.1:8765'),code=code,scope='ide'),host=args.host,port=args.port)
