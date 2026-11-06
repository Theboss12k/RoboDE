"""Disposable standard-edition runtime and gateways for real, local LLM evaluations.

Run with --output artifacts/... . Production workspaces/credentials are never loaded.
The relay stores final model answers and timings, not internal system prompt text.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import httpx
import uvicorn


async def main(args):
    os.environ['ROBOT_IDE_EDITION']='standard'
    # Explicit empty evaluation workspace: no production environment provider fallback.
    for key in ('AI_BASE_URL','AI_MODEL','AI_API_KEY'):
        os.environ.pop(key,None)
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='robode-real-models-') as directory:
        root=Path(directory).resolve()
        # main.py constructs a default app on import. Isolate that bootstrap too,
        # before importing it, as well as the explicit evaluation app below.
        os.environ['ROBOT_IDE_DATA_DIR']=str(root)
        from services.api.main import create_app
        from services.api.storage import Storage,atomic_json
        from web.gateway import create_gateway
        from fastapi import FastAPI,Request,Response
        from evals.fixtures import make_two_arm_project
        for pid in ('eval_desktop','eval_web','eval_business','eval_api'):
            make_two_arm_project(root,pid,'Evaluation · '+pid.removeprefix('eval_'))
        store=Storage(root)
        # The evaluation deliberately uses built-in motion, not a GPU/cloud/physical worker.
        atomic_json(store.runtime/'connections/motion.json',{'url':'http://127.0.0.1:19129','token_env':'ROBOT_DE_EVALUATION_UNUSED_TOKEN'})
        runtime=create_app(store,speed=100)
        relay=FastAPI()
        upstream=httpx.AsyncClient(timeout=310,trust_env=False)
        @relay.post('/api/chat')
        async def chat(request:Request):
            payload=await request.json();started=time.monotonic()
            response=await upstream.post(args.ollama_url.rstrip('/')+'/api/chat',json=payload)
            try:body=response.json()
            except ValueError:body={}
            from datetime import datetime,timezone
            entry={'recorded_at':datetime.now(timezone.utc).isoformat(),'model':payload.get('model'),'seconds':round(time.monotonic()-started,3),'http_status':response.status_code,
                   'system_sha256':hashlib.sha256(json.dumps([m for m in payload.get('messages',[]) if m.get('role')=='system']).encode()).hexdigest(),
                   'response':{k:body.get(k) for k in ('done','done_reason','total_duration','load_duration','prompt_eval_count','prompt_eval_duration','eval_count','eval_duration','error') if k in body},
                   'answer':body.get('message',{}).get('content','')}
            with (output/'inference.jsonl').open('a') as stream:stream.write(json.dumps(entry)+'\n')
            return Response(response.content,status_code=response.status_code,media_type='application/json')
        servers=[uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning')) for app,port in (
            (runtime,8886),(relay,11892),
            (create_gateway(upstream='http://127.0.0.1:8886',scope='ide',code='local-model-evaluation-code'),8085),
            (create_gateway(upstream='http://127.0.0.1:8886',scope='business',code='local-model-evaluation-code'),8086))]
        tasks=[asyncio.create_task(server.serve()) for server in servers]
        try:
            for _ in range(200):
                if all(server.started for server in servers):break
                for task in tasks:
                    if task.done():await task
                await asyncio.sleep(.05)
            if not all(server.started for server in servers):raise RuntimeError('Evaluation listeners did not start')
            print('Isolated model evaluation ready: IDE 8085, Business 8086. No production data or cloud compute.',flush=True)
            await asyncio.gather(*tasks)
        finally:
            for server in servers:server.should_exit=True
            await asyncio.gather(*tasks,return_exceptions=True)
            await upstream.aclose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('artifacts/nemotron-local-20261030'))
    parser.add_argument('--ollama-url',default='http://127.0.0.1:11434')
    asyncio.run(main(parser.parse_args()))
