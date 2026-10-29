"""Project -> editable plans -> atomic tasks, with immutable compile revisions."""
import uuid
import json
from fastapi import APIRouter
from pydantic import Field
from shared.models.domain import Contract, PlanDefinition, TaskDefinition, now
from services.api.storage import fingerprint, safe_id
from services.planning.definitions import compile_definition, validate_definition
from services.planning.workflow import Assignment
from services.planning.templates import draft_template_tasks
from services.ai_orchestrator.providers import get_provider
from services.ai_orchestrator.llm import json_answer
from services.ai_orchestrator.goal_constraints import validate_goal_outcome
import httpx
from fastapi import HTTPException


class CreatePlan(Contract):
    name: str = Field(min_length=1,max_length=120)
    goal: str = Field(default='',max_length=4000)


class EditPlan(CreatePlan):
    version: int
    tasks: list[TaskDefinition] = Field(max_length=144)


class DraftTasks(Contract):
    goals: list[Assignment] = Field(min_length=1,max_length=16)
    version: int
    adapter_id: str | None = None


class RefineTask(Contract):
    version: int
    instruction: str = Field(min_length=1,max_length=4000)
    adapter_id: str | None = None


def plans_router(store, controller):
    router = APIRouter(prefix='/api/projects/{project_id}/plan-definitions')

    @router.get('')
    async def list_plans(project_id:str):
        store.load_project(project_id)
        return [d for d in store.list_definitions(project_id) if not store.definition_archived(project_id,d.id)]

    @router.post('',status_code=201)
    async def create(project_id:str,data:CreatePlan):
        controller.ensure_idle(project_id)
        result = PlanDefinition(id=uuid.uuid4().hex[:12],project_id=project_id,name=data.name.strip(),goal=data.goal)
        validate_definition(result,{i['instance']['id'] for i in store.load_project(project_id)[1]})
        store.save_definition(result)
        return result

    @router.get('/{definition_id}')
    async def get(project_id:str,definition_id:str):
        return store.get_definition(project_id,definition_id)

    def current(project_id,definition_id,version):
        definition = store.get_definition(project_id,definition_id)
        if store.definition_archived(project_id,definition_id):
            raise ValueError('This plan was archived')
        if definition.version != version:
            raise HTTPException(409,'Plan changed in another editor; reload before saving')
        return definition

    @router.put('/{definition_id}')
    async def edit(project_id:str,definition_id:str,data:EditPlan):
        controller.ensure_idle(project_id)
        definition = current(project_id,definition_id,data.version)
        definition.name,definition.goal,definition.tasks = data.name.strip(),data.goal,data.tasks
        validate_definition(definition,{i['instance']['id'] for i in store.load_project(project_id)[1]})
        definition.version += 1
        definition.updated_at = now()
        store.save_definition(definition)
        return definition

    @router.delete('/{definition_id}')
    async def delete(project_id:str,definition_id:str):
        controller.ensure_idle(project_id)
        store.delete_definition(project_id,definition_id)
        return {'archived':True}

    @router.post('/{definition_id}/draft')
    async def draft(project_id:str,definition_id:str,data:DraftTasks):
        controller.ensure_idle(project_id)
        definition = current(project_id,definition_id,data.version)
        *_,session,_ = await controller.context(project_id)
        if any(session.held_objects.values()):
            raise ValueError('Reset the interrupted grasp before generating tasks')
        if data.adapter_id or controller.llm.all()['default_id']:
            from services.ai_orchestrator.task_drafting import draft_tasks
            from services.planning.workflow import ordered_assignments
            tasks=[]; terminal={}; states=await controller.states(session)
            for goal in ordered_assignments(data.goals):
                if goal.robot_id not in session.models:raise ValueError('Unknown assigned robot')
                try:
                    proposed=await draft_tasks(controller.llm,data.adapter_id,goal.prompt,session.models[goal.robot_id],goal.robot_id,session.objects,states[goal.robot_id].positions)
                except (httpx.HTTPError,KeyError,TypeError) as error:
                    raise HTTPException(502,'AI provider failed; no tasks were saved or executed') from error
                mapping={t.id:f'{goal.id}:{t.id}' for t in proposed}
                for task in proposed:
                    if any(d not in mapping for d in task.dependencies):raise ValueError('LLM draft references an unknown dependency')
                    task.id=mapping[task.id]
                    task.dependencies=[mapping[d] for d in task.dependencies] or [end for parent in goal.dependencies for end in terminal[parent]]
                    task.llm_adapter_id=controller.llm.resolve(data.adapter_id)['id']
                proposed=[TaskDefinition.model_validate(t.model_dump()) for t in proposed]
                used={d for t in proposed for d in t.dependencies}
                terminal[goal.id]=[t.id for t in proposed if t.id not in used]
                tasks.extend(proposed)
            controller.ensure_idle(project_id)
            definition=current(project_id,definition_id,data.version)
            candidate=definition.model_copy(deep=True);candidate.tasks=tasks
            # Check dependencies, capabilities, IK, limits and trajectory before saving a draft.
            checked=compile_definition(candidate,session.instances,session.models,session.objects,states,'draft',session.backend)
            if not checked.valid:raise ValueError('; '.join(c.message for c in checked.checks if c.status=='failed'))
            for goal in data.goals:
                validate_goal_outcome(goal.prompt,session.objects,checked,{t.id for t in tasks if t.id.startswith(goal.id+':')})
            definition.tasks=tasks
            if not definition.goal.strip():definition.goal='; '.join(g.prompt for g in data.goals)[:4000]
            definition.version+=1;definition.updated_at=now();store.save_definition(definition)
            return definition
        provider = get_provider(controller.llm,data.adapter_id)
        try:
            intents = {g.id:await provider.interpret(g.prompt,session.objects) for g in data.goals}
        except (httpx.HTTPError,KeyError,TypeError) as error:
            raise HTTPException(502,'AI provider failed; no tasks were saved or executed') from error
        controller.ensure_idle(project_id)
        definition = current(project_id,definition_id,data.version)
        definition.tasks = draft_template_tasks(data.goals,intents,session.instances,session.models,session.objects)
        validate_definition(definition,set(session.instances))
        for task in definition.tasks:
            task.llm_adapter_id = data.adapter_id or controller.llm.all()["default_id"]
        if not definition.goal.strip():
            definition.goal = '; '.join(g.prompt for g in data.goals)[:4000]
        definition.version += 1
        definition.updated_at = now()
        store.save_definition(definition)
        return definition

    @router.post('/{definition_id}/tasks/{task_id}/refine')
    async def refine(project_id:str,definition_id:str,task_id:str,data:RefineTask):
        controller.ensure_idle(project_id)
        definition = current(project_id,definition_id,data.version)
        task = next((t for t in definition.tasks if t.id==task_id),None)
        if not task:
            raise ValueError('Unknown task')
        _,instances,_,objects = store.load_project(project_id)
        invoke = controller.llm.adapter(data.adapter_id or task.llm_adapter_id)
        system = ('Refine exactly one atomic task. Return the entire TaskDefinition as JSON only. '
                  'Keep id and dependencies unchanged. Operations: move, grasp, release, verify, llm, command. Use task terminology. Preserve command schema. '
                  'No code. Motion parameters only for move. llm tasks have empty robot_id and require llm_input. '
                  f'Robot IDs: {[i["instance"]["id"] for i in instances]}. '
                  f'World objects: {[o.model_dump() for o in objects]}. '
                  f'Current task: {task.model_dump_json()}')
        response = await invoke(data.instruction,system)
        try:
            proposal = TaskDefinition.model_validate(json_answer(response['answer']))
        except (ValueError,TypeError) as error:
            raise ValueError('LLM returned an invalid task proposal; no changes saved') from error
        if proposal.id!=task.id or proposal.dependencies!=task.dependencies:
            raise ValueError('LLM changed task identity or dependencies; no changes saved')
        proposal.llm_adapter_id = controller.llm.resolve(data.adapter_id or task.llm_adapter_id)['id']
        candidate = definition.model_copy(deep=True)
        candidate.tasks = [proposal if t.id==task_id else t for t in candidate.tasks]
        validate_definition(candidate,{i['instance']['id'] for i in instances})
        controller.ensure_idle(project_id)
        current(project_id,definition_id,data.version)
        # Return a reviewable proposal. The normal Save action accepts it.
        return {'task':proposal,'answer':response}

    @router.post('/{definition_id}/compile',status_code=201)
    async def compile_plan(project_id:str,definition_id:str):
        controller.ensure_idle(project_id)
        definition = store.get_definition(project_id,definition_id)
        if store.definition_archived(project_id,definition_id):
            raise ValueError('This plan was archived')
        for task in definition.tasks:
            if task.operation == 'llm':
                task.llm_adapter_id = controller.llm.resolve(task.llm_adapter_id)['id']
        snapshot = await controller.snapshot(project_id)
        session = controller.sessions[project_id]
        if any(session.held_objects.values()):
            raise ValueError('Reset the interrupted grasp before compiling')
        revision = compile_definition(definition,session.instances,session.models,session.objects,
                                      await controller.states(session),fingerprint(snapshot),session.backend)
        controller.ensure_idle(project_id)
        if store.get_definition(project_id,definition_id).version != definition.version:
            raise HTTPException(409,'Plan changed while compiling; compile the current version')
        store.save_plan(revision,snapshot)
        return revision

    @router.get('/{definition_id}/revisions')
    async def revisions(project_id:str,definition_id:str):
        store.get_definition(project_id,definition_id)
        folder = store.project_folder(project_id)/'plans'/safe_id(definition_id)/'revisions'
        return [{'id':p.parent.name} for p in sorted(folder.glob('*/plan.json'),key=lambda p:p.stat().st_mtime,reverse=True)]

    return router
