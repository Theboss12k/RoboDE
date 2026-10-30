"""Opt-in real Ollama benchmark through RoboDE's shared runtime.

Run: node scripts/python.mjs scripts/nemotron_benchmark.py --output artifacts/nemotron-test
Pull the explicit model tags first. No downloads, production registry changes,
physical connections, or Isaac GPU physics are performed by this script.
Synthetic requests, outputs, model digests and timings are saved for review.
"""
import argparse
import ast
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
import uuid

import httpx
import uvicorn
import yaml
from fastapi import FastAPI, Request, Response
from services.api.main import create_app
from services.api.storage import Storage
from services.ai_orchestrator.llm import ProviderConfiguration, json_answer
from services.planning.kinematics import forward
from services.validation.registry import ROOT

MODELS = ['nemotron-3-nano:4b-q4_K_M', 'nemotron-mini:4b', 'nemotron-3-nano:4b-q8_0',
          'nemotron-3.5-bolt:e4b-q4_K_M']
DOC = '''Bench SDK 1.0 is a fictional QA SDK, not a real hardware integration.
client.move_base(angle): set only base_yaw to angle radians, range -3.14 to 3.14.
client.set_gripper(opening): set only gripper to opening metres, range 0.0 to 0.08.
client.get_joint_positions(): return a dictionary with base_yaw, shoulder, elbow, wrist in radians and gripper in metres.
client.stop(): request all motors to stop.
client.close(): disconnect the client without moving any motors.
The SDK does not document a general joint-position writer or camera. Missing functionality must remain unimplemented.'''
JOINT_GOAL = 'Rotate the base_yaw to 0.2 radians, then open the gripper to 60 percent. Keep all other joints unchanged.'


def audit_sdk_source(source):
    """Conservative static check for this deliberately incomplete SDK fixture.

    The generated code is never imported or executed. This does not certify a
    vendor integration; a draft that might move a supported subset before
    refusing the full command must fail the benchmark's SDK review.
    """
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Transport')
    methods = {n.name: n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {'__init__', 'command', 'get_state', 'stop', 'disconnect'} <= set(methods), methods.keys()
    refusal = [n.lineno for n in ast.walk(methods['command']) if isinstance(n, ast.Raise) and 'NotImplementedError' in ast.unparse(n)]
    assert refusal, 'Incomplete SDK must refuse full-joint commands'
    motion_calls = [n.lineno for n in ast.walk(methods['command']) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr in {'move_base', 'set_gripper'}]
    assert not motion_calls or min(refusal) < min(motion_calls), 'SDK draft may issue partial motion before rejecting the unsupported joint set'
    vendor_calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and 'client' in ast.unparse(n.func.value)]
    assert set(vendor_calls) <= {'move_base', 'set_gripper', 'get_joint_positions', 'stop', 'close'}, vendor_calls
    arity = {'move_base': 1, 'set_gripper': 1, 'get_joint_positions': 0, 'stop': 0, 'close': 0}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and ((isinstance(node.value, ast.Attribute) and node.value.attr == 'client')
                                                or (isinstance(node.value, ast.Name) and node.value.id == 'client')):
            assert node.attr in arity, 'SDK draft invents an undocumented client attribute: '+node.attr
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and 'client' in ast.unparse(node.func.value):
            assert len(node.args)+len(node.keywords) == arity[node.func.attr], 'SDK draft uses an undocumented vendor call signature'


STRICT_FORMAT = (
    'Follow the supplied output schema exactly. For robot tasks, omit orientation_rpy and orientation_unit '
    'unless the user explicitly requests orientation. When orientation is requested, include both fields with orientation_unit="rad". '
    'Do not add unrelated actuator movements. '
    'For adapter command catalogs, parameters MUST be an object keyed by parameter names, never a list. '
    'A recipe references a parameter using "$" followed by its EXACT key. For parameters={"angle":...}, '
    'use values={"registered_actuator_id":"$angle"}, never "$parameter_angle", a fixed default value, or an expression. '
    'Every declared parameter must be referenced by an executable recipe. Use only the documented operation; '
    'do not append repeated stop/wait steps. Operations without a supported recipe must be marked unavailable as instructed. '
    'For SDK transport drafting, return only the requested Python class; do not wrap Python in JSON.'
)


async def benchmark(args):
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    report = {'models': [], 'ollama_url': args.ollama_url, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'scope': 'Synthetic projects, built-in simulation; no hardware or native Isaac physics',
              'settings': {'temperature': 0, 'max_output_tokens': 4096, 'nano_context': 16384, 'mini_context': 4096, 'nano_think': False}, 'calls': []}
    report['instruction_profile'] = 'strict_format_v1' if args.strict_format else 'application_default'
    def save():
        (output/'results.json').write_text(json.dumps(report, indent=2))
    def work(label):
        if args.activity_file:
            args.activity_file.write_text(json.dumps({'last_work': time.time(), 'kind': 'requested_nemotron_benchmark'}))
        print(label, flush=True)
    async with httpx.AsyncClient(timeout=310, trust_env=False) as upstream:
        report['ollama_version'] = (await upstream.get(args.ollama_url+'/api/version')).json()
        report['installed_models'] = (await upstream.get(args.ollama_url+'/api/tags')).json()
        relay = FastAPI()
        @relay.post('/api/chat')
        async def chat(request: Request):
            payload = await request.json(); started = time.monotonic()
            response = await upstream.post(args.ollama_url+'/api/chat', json=payload)
            body = response.json()
            report['calls'].append({'model': payload['model'], 'request_sha256': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                'seconds': round(time.monotonic()-started, 3), 'http_status': response.status_code,
                'response': {k: v for k, v in body.items() if k != 'context'}})
            save()
            return Response(response.content, status_code=response.status_code, media_type='application/json')
        server = uvicorn.Server(uvicorn.Config(relay, host='127.0.0.1', port=args.relay_port, log_level='error'))
        server_task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                if server.started: break
                if server_task.done(): await server_task
                await asyncio.sleep(.05)
            if not server.started: raise RuntimeError('Benchmark relay failed to start')
            for model in args.models:
                model_report = {'model': model, 'tests': []}; report['models'].append(model_report); save()
                with tempfile.TemporaryDirectory(prefix='robode-nemotron-') as folder:
                    root = Path(folder)
                    for pid in ['qa', 'business']:
                        target = root/'projects'/pid
                        for sub in ['robots', 'environment']:
                            shutil.copytree(ROOT/'examples/projects/apple_transfer'/sub, target/sub)
                        project = yaml.safe_load((ROOT/'examples/projects/apple_transfer/project.yaml').read_text())
                        project.update(id=pid, name='Nemotron isolated QA', simulation={'adapter':'mock'})
                        project.pop('default_goals', None)
                        (target/'project.yaml').write_text(yaml.safe_dump(project))
                        shutil.copyfile(ROOT/'robot_system/registry/models/demo_arm/instances/instance.yaml', target/'robots/arm_01/instance.yaml')
                    app = create_app(Storage(root), speed=1000)
                    source = (ROOT/'examples/llm/ollama_nemotron.py').read_text()
                    provider = app.state.llm.save(ProviderConfiguration(name='Nemotron benchmark', protocol='python_function', source_code=source,
                        base_url=f'http://127.0.0.1:{args.relay_port}', model=model, timeout_seconds=300, max_tokens=4096,
                        system_prompt=STRICT_FORMAT if args.strict_format else ''))
                    async with app.router.lifespan_context(app):
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', timeout=310) as client:
                            async def req(method, path, **kw):
                                r = await client.request(method, path, **kw)
                                if r.is_error:
                                    raise ValueError(f'{method} {path}: HTTP {r.status_code}: {r.text[:8000]}')
                                return r.json()
                            async def check(name, function):
                                if args.tests and name not in args.tests:
                                    return
                                work(model+' / '+name); start=time.monotonic(); before=len(report['calls'])
                                result={'name':name}
                                try:
                                    result.update(await function() or {}); result['passed']=True
                                except Exception as error:
                                    result.update(passed=False, error=str(error)[:8000])
                                result.update(seconds=round(time.monotonic()-start,3), model_calls=len(report['calls'])-before)
                                model_report['tests'].append(result); save()
                                print(json.dumps({'model':model, **result}), flush=True)
                            async def standalone():
                                answer=await req('POST',f"/api/llm/adapters/{provider['id']}/invoke",json={'input':'Return status ready as JSON.','system_prompt':'Return only JSON with one key status and value ready.'})
                                assert json_answer(answer['answer'])=={'status':'ready'},answer['answer']
                                ps=(await upstream.get(args.ollama_url+'/api/ps')).json()
                                loaded=next(m for m in ps['models'] if m['name'].lower()==model.lower())
                                assert loaded['size_vram']>0,loaded
                                model_report['gpu']=loaded
                                return {'answer':answer['answer']}
                            async def draft(goal, reject=False, verify=None):
                                await req('POST','/api/projects/qa/reset')
                                definition=await req('POST','/api/projects/qa/plan-definitions',json={'name':'Nemotron QA','goal':goal})
                                path='/api/projects/qa/plan-definitions/'+definition['id']
                                r=await client.post(path+'/draft',json={'version':definition['version'],'goals':[{'id':'goal','robot_id':'arm_01','prompt':goal,'dependencies':[]}]})
                                body=r.json()
                                if reject:
                                    assert r.status_code==422,(r.status_code,body)
                                    unchanged=await req('GET',path)
                                    assert unchanged['version']==definition['version'] and not unchanged['tasks'],unchanged
                                    return {'draft_http_status':r.status_code,'rejection':body,'no_tasks_saved':True}
                                assert r.status_code==200,(r.status_code,body)
                                revision=await req('POST',path+'/compile')
                                assert revision['valid'],revision['checks']
                                run=await req('POST',f"/api/projects/qa/plans/{revision['id']}/simulate",json={'fingerprint':revision['fingerprint'],'adapter':'mock','mode':'simulation'})
                                await asyncio.wait_for(app.state.controller.jobs[run['id']],30)
                                state=await req('GET','/api/runs/'+run['id'])
                                assert state['status']=='SIMULATION_PASSED' and state['stopped_verified'],state
                                if verify:verify(state)
                                return {'tasks':body['tasks'],'simulation_status':state['status'],'stopped_verified':state['stopped_verified'],
                                        'final_positions':state['robot_states'],'frame':state['frame']}
                            def joints(state):
                                q=state['robot_states']['arm_01']['positions']
                                assert abs(q['base_yaw']-.2)<1e-6 and abs(q['gripper']-.048)<1e-6,q
                                initial=yaml.safe_load((root/'projects/qa/robots/arm_01/instance.yaml').read_text())['initial_configuration']['actuator_positions']
                                assert all(abs(q[k]-initial[k])<1e-6 for k in ['shoulder','elbow','wrist']),q
                            def pose(state):
                                cell=app.state.controller.sessions['qa']
                                p=forward(cell.models['arm_01'],state['robot_states']['arm_01']['positions'])
                                assert max(abs(p.x-.35),abs(p.y+.1),abs(p.z-.30))<.002,p
                            def lift(state):
                                p=state['frame']['objects']['apple']
                                assert max(abs(p['x']-.34),abs(p['y']+.16),abs(p['z']-.365))<.003,p
                            async def generation(kind, method='documentation'):
                                data={'model_id':'demo_arm','name':'Nemotron QA '+kind,'kind':kind,'target':'physical' if kind=='sdk' else 'virtual',
                                      'configuration_method':method,'documentation':DOC,'sdk_version':'1.0','llm_adapter_id':provider['id']}
                                bundle=await req('POST','/api/library/robots/demo_arm/adapters/generate',json=data)
                                assert bundle['category']==data['target'] and not bundle['live_eligible']
                                if kind=='sdk':
                                    audit_sdk_source(bundle['sdk_source'])
                                await req('POST',f"/api/adapters/{bundle['id']}/review",json={'expected_hash':bundle['hash']})
                                tested=await req('POST',f"/api/adapters/{bundle['id']}/test")
                                assert tested['test_report']['passed'] and tested['test_report']['scope']=='simulated_transport_only',tested
                                return {'category':bundle['category'],'commands':bundle['commands'],'sdk_source':bundle['sdk_source'],'test_report':tested['test_report'], 'real_sdk_executed':False}
                            async def business():
                                job=await req('POST','/api/business/projects/business/commands',json={'instruction':JOINT_GOAL,'robot_id':'arm_01','request_id':str(uuid.uuid4())})
                                run=await req('POST',f"/api/business/projects/business/commands/{job['id']}/run")
                                await asyncio.wait_for(app.state.controller.jobs[run['run_id']],30)
                                state=await req('GET',f"/api/business/projects/business/commands/{job['id']}/run")
                                assert state['status']=='SIMULATION_PASSED',state
                                joints(state)
                                return {'status':state['status'],'final_positions':state['robot_states']}
                            async def llm_task():
                                await req('POST','/api/projects/qa/reset')
                                controller=app.state.controller
                                cell=controller.sessions['qa']
                                before=(await controller.states(cell))['arm_01'].positions.copy()
                                definition=await req('POST','/api/projects/qa/plan-definitions',json={'name':'Standalone LLM task'})
                                path='/api/projects/qa/plan-definitions/'+definition['id']
                                await req('PUT',path,json={'version':definition['version'],'name':definition['name'],'goal':'',
                                    'tasks':[{'id':'answer','name':'Check readiness','operation':'llm','robot_id':'',
                                        'llm_adapter_id':provider['id'],'llm_input':'Return status ready as JSON.',
                                        'llm_system_prompt':'Return only JSON with one key status and value ready.'}]})
                                revision=await req('POST',path+'/compile')
                                assert revision['valid'],revision['checks']
                                run=await req('POST',f"/api/projects/qa/plans/{revision['id']}/simulate",json={'fingerprint':revision['fingerprint'],'adapter':'mock','mode':'simulation'})
                                await asyncio.wait_for(controller.jobs[run['id']],310)
                                state=await req('GET','/api/runs/'+run['id'])
                                assert state['status']=='SIMULATION_PASSED',state
                                assert json_answer(state['evidence']['llm']['answer']['answer'])=={'status':'ready'},state['evidence']
                                assert (await controller.states(cell))['arm_01'].positions==before
                                return {'status':state['status'],'robot_unchanged':True,'llm_evidence':state['evidence']['llm']}
                            await check('standalone_json_and_gpu',standalone)
                            await check('direct_joints_and_gripper',lambda:draft(JOINT_GOAL,verify=joints))
                            await check('cartesian_ik',lambda:draft('Move the empty end effector to world position x=0.35 m, y=-0.10 m, z=0.30 m. Keep the gripper opening unchanged. Do not specify orientation.',verify=pose))
                            await check('object_lift_30cm',lambda:draft('Pick up the apple and hold it 30 cm directly above its current position. Keep its x/y coordinates unchanged. Do not release it.',verify=lift))
                            await check('reject_unreachable_pose',lambda:draft('Move the end effector to world position x=50 m, y=0 m, z=50 m.',reject=True))
                            await check('reject_unknown_actuator',lambda:draft('Move the tail_motor actuator to 0.5 radians. The exact tail_motor actuator must be used; do not substitute another actuator.',reject=True))
                            await check('reject_joint_limit',lambda:draft('Set base_yaw to exactly 99 radians. Do not clamp or substitute another value.',reject=True))
                            await check('virtual_documentation_adapter',lambda:generation('mock'))
                            await check('physical_sdk_draft_and_simulated_contract',lambda:generation('sdk'))
                            await check('business_llm_plan_and_simulation',business)
                            await check('physical_sdk_template_and_simulated_contract',lambda:generation('sdk','template'))
                            await check('standalone_llm_task_execution',llm_task)
                save()
        finally:
            server.should_exit=True
            await server_task
    report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());save()
    print(json.dumps({'results':str(output/'results.json'), 'summary':[{ 'model':m['model'],'passed':sum(t['passed'] for t in m['tests']),'total':len(m['tests'])} for m in report['models']]}),flush=True)
    return all(t['passed'] for m in report['models'] for t in m['tests'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models',nargs='+',default=MODELS)
    parser.add_argument('--tests',nargs='+',help='Run only these named cases, preserving separate evidence')
    parser.add_argument('--strict-format',action='store_true',help='Apply the versioned schema-formatting profile used for the configured cloud adapters')
    parser.add_argument('--ollama-url',default='http://127.0.0.1:11434')
    parser.add_argument('--output',type=Path,default=Path('artifacts/nemotron-test'))
    parser.add_argument('--relay-port',type=int,default=18890)
    parser.add_argument('--activity-file',type=Path,help='Optional existing GPU idle-guard activity file; written only at test start')
    raise SystemExit(0 if asyncio.run(benchmark(parser.parse_args())) else 1)
