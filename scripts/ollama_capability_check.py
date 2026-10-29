"""Additional real-model pose/IK, manipulation and rejection checks (opt-in)."""
import json
import os
from pathlib import Path
import time
import httpx

FOLDER=Path('artifacts/ollama-20261029')


def main():
    skip_virtual=os.environ.get('OLLAMA_QA_SKIP_ADAPTERS')=='1'
    results=[r for r in json.loads((FOLDER/'capability-results.json').read_text()) if r['name']=='Phi-4 virtual adapter generation and transport contract'] if skip_virtual else []
    with httpx.Client(base_url='http://127.0.0.1:18877',timeout=310) as client:
        def save():
            (FOLDER/'capability-results.json').write_text(json.dumps(results,indent=2))
        def check(name,goal,expected_valid,verify=None):
            start=time.monotonic()
            result={'name':name,'goal':goal}
            try:
                reset=client.post('/api/projects/capabilities/reset');reset.raise_for_status()
                definition=client.post('/api/projects/capabilities/plan-definitions',json={'name':name,'goal':goal}).json()
                path='/api/projects/capabilities/plan-definitions/'+definition['id']
                response=client.post(path+'/draft',json={'version':definition['version'],'goals':[{'id':'goal','robot_id':'arm_01','prompt':goal,'dependencies':[]}]})
                result.update(draft_status=response.status_code,draft=response.json())
                if not expected_valid:
                    assert response.status_code==422,response.text
                    unchanged=client.get(path).json()
                    assert unchanged['version']==definition['version'] and not unchanged['tasks']
                    result['unchanged_on_rejection']=True
                else:
                    response.raise_for_status()
                    compiled=client.post(path+'/compile');compiled.raise_for_status();plan=compiled.json()
                    run=client.post(f"/api/projects/capabilities/plans/{plan['id']}/simulate",json={'fingerprint':plan['fingerprint'],'adapter':'mock','mode':'simulation'})
                    run.raise_for_status();rid=run.json()['id']
                    deadline=time.monotonic()+20
                    while time.monotonic()<deadline:
                        state=client.get('/api/runs/'+rid).json()
                        if state['status'] in ['SIMULATION_PASSED','FAILED','CANCELLED','TIMED_OUT']:break
                        time.sleep(.1)
                    assert state['status']=='SIMULATION_PASSED',state
                    if verify:verify(state)
                    result.update(run_id=rid,status=state['status'],final_frame=state['frame'],final_positions=state['robot_states'])
                result['passed']=True
            except Exception as error:
                result.update(passed=False,error=str(error))
            result['duration_seconds']=round(time.monotonic()-start,3)
            results.append(result);save();print(name+': '+('PASS' if result['passed'] else 'FAIL '+result['error'][:900]),flush=True)

        if not skip_virtual:
            # Exercise the virtual generation branch against the same real local model.
            start=time.monotonic()
            result={'name':'Phi-4 virtual adapter generation and transport contract'}
            try:
                physical=next(b for b in client.get('/api/library/adapters').json() if b['category']=='physical')
                response=client.post('/api/library/robots/demo_arm/adapters/generate',json={
                    'model_id':'demo_arm','name':'Phi-4 virtual documentation adapter','kind':'mock','target':'virtual',
                    'configuration_method':'documentation','documentation':physical['documentation'],'sdk_version':'1.0'})
                response.raise_for_status();bundle=response.json()
                client.post(f"/api/adapters/{bundle['id']}/review",json={'expected_hash':bundle['hash']}).raise_for_status()
                tested=client.post(f"/api/adapters/{bundle['id']}/test");tested.raise_for_status()
                assert tested.json()['test_report']['passed'] and tested.json()['test_report']['scope']=='simulated_transport_only'
                result.update(passed=True,adapter_id=bundle['id'],report=tested.json()['test_report'])
            except Exception as error:result.update(passed=False,error=str(error))
            result['duration_seconds']=round(time.monotonic()-start,3);results.append(result);save()
            print(result['name']+': '+('PASS' if result['passed'] else 'FAIL '+result['error'][:900]),flush=True)

        def pose(state):
            from services.validation.registry import load_model,MODEL_ROOT
            from services.planning.kinematics import forward
            position=forward(load_model(MODEL_ROOT/'demo_arm'),state['robot_states']['arm_01']['positions'])
            assert abs(position.x-.35)<.002 and abs(position.y+.1)<.002 and abs(position.z-.3)<.002,position
        check('Phi-4 Cartesian pose through IK','Move the empty end effector to world position x=0.35 m, y=-0.10 m, z=0.30 m. Keep the gripper opening unchanged. Do not specify orientation.',True,pose)
        initial=client.get('/api/projects/capabilities').json()
        apple=next(o for o in initial['objects'] if o['id']=='apple')
        def held(state):
            p=state['frame']['objects']['apple']
            assert abs(p['x']-apple['position']['x'])<.003 and abs(p['y']-apple['position']['y'])<.003,p
            assert abs(p['z']-apple['position']['z']-.30)<.003,p
        check('Phi-4 object lift 30 cm','Pick up the apple and hold it 30 cm directly above its current position. Keep its x/y coordinates unchanged. Do not release it.',True,held)
        check('Phi-4 unreachable pose rejection','Move the end effector to world position x=50 m, y=0 m, z=50 m.',False)
        check('Phi-4 unknown actuator rejection','Move the tail_motor actuator to 0.5 radians. The exact tail_motor actuator must be used; do not substitute another actuator.',False)
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)


if __name__=='__main__':main()
