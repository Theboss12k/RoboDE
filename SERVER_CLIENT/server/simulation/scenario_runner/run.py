"""Run task examples in an isolated built-in simulator, with immutable output artifacts."""
import argparse
import asyncio
import json
import math
import shutil
import tempfile
import uuid
from pathlib import Path
from services.ai_orchestrator.providers import TemplateProvider
from services.ai_orchestrator.llm import LLMRegistry
from services.api.storage import Storage, fingerprint, safe_id
from services.execution.controller import SimulationController
from services.planning.definitions import compile_definition
from services.planning.templates import draft_template_tasks
from services.planning.workflow import Assignment
from services.validation.registry import ROOT, component, read_yaml
from shared.models.domain import PlanDefinition

EXAMPLES=ROOT/'examples'


def example_names():
    return [p.stem for p in sorted((EXAMPLES/'plans').glob('*.json'))]


def load_example(name):
    if name not in example_names():raise ValueError(f'Unknown example: {name}. Use --list')
    return PlanDefinition.model_validate_json((EXAMPLES/'plans'/f'{name}.json').read_text())


def prepare_project(store,project_id,destination):
    """Copy definitions/assets only; no user runs, simulator state, profiles or secrets."""
    safe_id(project_id)
    curated=EXAMPLES/'projects'/project_id
    source=curated if curated.is_dir() else store.project_folder(project_id)
    project=read_yaml(source/'project.yaml')
    project['simulation']={'adapter':'mock'}
    target=destination.project_folder(project_id);target.mkdir(parents=True)
    import yaml
    (target/'project.yaml').write_text(yaml.safe_dump(project,sort_keys=False))
    for relative in project['robots']:
        path=component(source,relative);out=target/relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,out)
        model_id=read_yaml(path)['robot_model']['id'];safe_id(model_id)
        model_source=EXAMPLES/'models'/model_id
        if not model_source.is_dir():model_source=store.model_folder(model_id)
        # Built-ins resolve from the registry. Imported/curated models stay local to this run.
        if model_source.is_relative_to(EXAMPLES) or model_source.is_relative_to(store.runtime):
            model_target=destination.runtime/'imported_models'/model_id
            if not model_target.exists():shutil.copytree(model_source,model_target)
    world=component(source,project['environment']);out=target/project['environment'];out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(world,out)
    if (world.parent/'assets').is_dir():shutil.copytree(world.parent/'assets',out.parent/'assets')
    return project


async def scenario(project_id=None,prompt=None,speed=10,example=None,output=None,allow_llm=False,source_store=None):
    if not math.isfinite(speed) or not 0<speed<=1000:raise ValueError('speed must be between 0 and 1000')
    definition=load_example(example) if example else None
    project_id=project_id or (definition.project_id if definition else 'apple_transfer')
    if definition and any(t.operation=='llm' for t in definition.tasks) and not allow_llm:
        raise ValueError('LLM example contacts your configured provider. Run with --allow-llm after configuring an adapter')
    with tempfile.TemporaryDirectory(prefix='robot-ide-example-') as folder:
        store=Storage(Path(folder));source=source_store or Storage();project=prepare_project(source,project_id,store)
        runtime=SimulationController(store,speed=speed)
        try:
            if allow_llm:
                from dotenv import load_dotenv
                load_dotenv(ROOT/'.env')
                runtime.llm=LLMRegistry(source)
            await runtime.reset(project_id)
            _,_,_,session,_=await runtime.context(project_id)
            if definition is None:
                goals=[Assignment.model_validate(g) for g in (project.get('default_goals') or project.get('workflow_tasks') or [])] if prompt is None else []
                if not goals:goals=[Assignment(id='goal_1',robot_id=next(iter(session.instances)),prompt=prompt or project['default_prompt'])]
                provider=TemplateProvider();intents={g.id:await provider.interpret(g.prompt,session.objects) for g in goals}
                definition=PlanDefinition(id=uuid.uuid4().hex[:12],project_id=project_id,name='Example plan',goal='; '.join(g.prompt for g in goals),
                    tasks=draft_template_tasks(goals,intents,session.instances,session.models,session.objects))
            definition=definition.model_copy(deep=True);definition.project_id=project_id
            for task in definition.tasks:
                if task.operation=='llm':task.llm_adapter_id=runtime.llm.resolve(task.llm_adapter_id)['id']
            store.save_definition(definition)
            snapshot=await runtime.snapshot(project_id)
            revision=compile_definition(definition,session.instances,session.models,session.objects,await runtime.states(session),fingerprint(snapshot),'mock')
            store.save_plan(revision,snapshot)
            for check in revision.checks:print(f'[{check.status}] {check.label}: {check.message}')
            destination=Path(output) if output else ROOT/'artifacts/examples'/(example or project_id)/uuid.uuid4().hex[:12]
            destination.mkdir(parents=True,exist_ok=True)
            shutil.copytree(store.project_folder(project_id)/'plans'/definition.id,destination/'plan',dirs_exist_ok=True)
            if not revision.valid:
                print(f'Validation failed. Artifacts: {destination.resolve()}');return 1
            run=await runtime.execute_registered_plan(revision.id,revision.fingerprint,project_id)
            await runtime.jobs[run.id]
            (destination/'run.json').write_text(run.model_dump_json(indent=2)+'\n')
            print(f'\n{run.status.value}: {len(definition.tasks)} tasks. Artifacts: {destination.resolve()}')
            return 0 if run.evidence.get('postcondition_passed') else 1
        finally:
            await runtime.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list',action='store_true',help='List rewritten task examples')
    parser.add_argument('--example',choices=example_names())
    parser.add_argument('--project',help='Curated example project, or a project to copy into an isolated preview')
    parser.add_argument('--prompt',help='Offline template goal, used instead of a saved example')
    parser.add_argument('--speed',type=float,default=10)
    parser.add_argument('--output',type=Path,help='Output artifact directory; never the source project')
    parser.add_argument('--allow-llm',action='store_true',help='Allow the LLM example to contact a configured provider')
    args=parser.parse_args()
    if args.list:
        for name in example_names():print(f'{name}: {load_example(name).name}')
        return 0
    if args.example and args.prompt:parser.error('Choose --example or --prompt')
    try:return asyncio.run(scenario(args.project,args.prompt,args.speed,args.example,args.output,args.allow_llm))
    except (ValueError,FileNotFoundError) as error:parser.error(str(error))


if __name__=='__main__':raise SystemExit(main())
