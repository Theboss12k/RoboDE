"""Exercise standardized tasks through an adapter's isolated simulated transport."""
import argparse
import asyncio
import httpx
from examples.run_plan import request
from simulation.scenario_runner.run import load_example


async def run(args):
    definition=load_example(args.example)
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8765',timeout=60) as client:
        session=await request(client,'POST',f'/api/projects/{args.project}/controls',{
            'robot_id':args.robot,'adapter_id':args.adapter,'mode':'test'})
        try:
            for task in definition.tasks:
                if task.command is None:continue
                result=await request(client,'POST',f'/api/controls/{session["id"]}/standard-command',task.command.model_dump(mode='json',exclude_none=True))
                print(f'{task.name}: SIMULATED feedback {result["feedback"]["positions"]}')
        finally:
            try:
                stopped=await request(client,'POST',f'/api/controls/{session["id"]}/stop')
                print(f'Stop requested; stopped confirmed: {stopped["stopped_verified"]}')
            finally:await request(client,'DELETE',f'/api/controls/{session["id"]}')
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',default='apple_transfer')
    parser.add_argument('--robot',default='arm_01')
    parser.add_argument('--adapter',default='mock',help='Built-in virtual adapter or reviewed/tested generated adapter ID')
    parser.add_argument('--example',choices=['wave','joint_control','gripper_control'],default='wave')
    try:return asyncio.run(run(parser.parse_args()))
    except (ValueError,httpx.HTTPError) as error:parser.exit(1,f'{error}\n')


if __name__=='__main__':raise SystemExit(main())
