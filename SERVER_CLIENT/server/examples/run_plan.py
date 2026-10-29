"""Create an editable plan, compile it, then optionally simulate its exact revision.

Run as a module from the repository root; this client uses the running local API.
"""
import argparse
import asyncio
import httpx
from simulation.scenario_runner.run import example_names,load_example


async def request(client,method,path,body=None):
    response=await client.request(method,path,json=body)
    if not response.is_success:raise ValueError(f'{method} {path}: {response.text}')
    return response.json()


async def create_plan(client,example,project_id=None):
    definition=load_example(example);project_id=project_id or definition.project_id
    base=f'/api/projects/{project_id}/plan-definitions'
    created=await request(client,'POST',base,{'name':definition.name,'goal':definition.goal})
    saved=await request(client,'PUT',base+'/'+created['id'],{
        'version':created['version'],'name':definition.name,'goal':definition.goal,
        'tasks':[task.model_dump(mode='json',exclude_none=True) for task in definition.tasks]})
    revision=await request(client,'POST',base+'/'+saved['id']+'/compile')
    return saved,revision


async def run(args):
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8765',timeout=30) as client:
        definition,revision=await create_plan(client,args.example,args.project)
        print(f'Project {revision["project_id"]} → Plan {definition["id"]} → {len(definition["tasks"])} Tasks')
        print(f'Immutable revision: {revision["id"]}')
        for check in revision['checks']:print(f'[{check["status"]}] {check["message"]}')
        if not revision['valid']:return 1
        if not args.simulate:return 0
        run=await request(client,'POST',f'/api/projects/{revision["project_id"]}/plans/{revision["id"]}/simulate',{
            'fingerprint':revision['fingerprint'],'adapter':revision['adapter'],'mode':'simulation'})
        try:
            while not run['finished_at']:
                await asyncio.sleep(.25)
                run=await request(client,'GET',f'/api/runs/{run["id"]}')
            print(f'{run["status"]}; stopped confirmed: {run["stopped_verified"]}')
            return 0 if run['status']=='SIMULATION_PASSED' else 1
        finally:
            if not run['finished_at']:
                await request(client,'POST',f'/api/runs/{run["id"]}/stop')
                print('Stop requested; read the run for measured stopped confirmation.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example',choices=example_names(),default='wave')
    parser.add_argument('--project',help='Explicit target project with matching robot IDs/models and scene')
    parser.add_argument('--simulate',action='store_true',help='Start simulation after compilation; otherwise leave a reviewable plan')
    args=parser.parse_args()
    try:return asyncio.run(run(args))
    except (ValueError,httpx.HTTPError) as error:parser.exit(1,f'{error}\n')


if __name__=='__main__':raise SystemExit(main())
