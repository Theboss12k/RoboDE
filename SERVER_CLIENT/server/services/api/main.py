from typing import Literal
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import httpx
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from shared.models.domain import Contract, WorldObject
from services.ai_orchestrator.providers import get_provider
from services.api.storage import Storage, fingerprint
from services.api.model_library import model_library_router
from services.api.llm import llm_router
from services.api.isaac import isaac_router
from services.api.plans import plans_router
from services.api.assets import assets_router, validate_asset_refs
from services.api.adapters import adapters_router
from services.api.configuration import configuration_router
from services.adapters.generation import AdapterRegistry
from services.adapters.controls import ManualControls
from services.execution.controller import SimulationController
from services.planning.planner import build_plan
from services.planning.workflow import Assignment, build_workflow
from robot_system.registry.models.demo_arm.adapters.isaac_sim.adapter import WorkerUnavailable
from services.validation.registry import ROOT, REPOSITORY_ROOT, registry, validate_positions

load_dotenv(ROOT / ".env")
load_dotenv(REPOSITORY_ROOT / ".env")


class PlanRequest(Contract):
    prompt: str = Field(min_length=1, max_length=4000)
    robot_id: str | None = None


class ExecuteRequest(Contract):
    fingerprint: str
    adapter: str | None = None
    mode: str = "simulation"


class ProjectRequest(Contract):
    name: str = Field(min_length=1, max_length=80)
    source: str = "apple_transfer"


class InitialRequest(Contract):
    positions: dict[str, float]
    robot_id: str | None = None


class WorkflowRequest(Contract):
    tasks: list[Assignment] = Field(min_length=1, max_length=16)


class SimulationRequest(Contract):
    adapter: str


class RobotRequest(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    name: str = Field(min_length=1, max_length=80)
    base_pose: dict[str, float]
    model_id: str | None = None
    initial_positions: dict[str,float] | None = None
    adapter_id: str = 'mock'
    category: Literal['physical','virtual'] | None = None


class WorldRequest(Contract):
    objects: list[WorldObject]


def create_app(storage: Storage | None = None, speed: float = 1.0):
    store = storage or Storage()
    controller = SimulationController(store, speed=speed)
    adapters = AdapterRegistry(store)
    controls = ManualControls(adapters,controller)

    @asynccontextmanager
    async def lifespan(app):
        store.recover_interrupted_runs()
        yield
        await controls.close()
        await controller.close()
        await controller.local_isaac.close()
        await controller.gpu.close()

    app = FastAPI(title="RoboDE Runtime", version="0.4.0", lifespan=lifespan)
    app.state.controller = controller
    app.state.storage = store
    from services.api.recordings import recordings_router
    app.include_router(recordings_router(controller))
    app.include_router(isaac_router(store,controller,controls))
    app.include_router(plans_router(store,controller))
    app.include_router(assets_router(store,controller))
    app.include_router(adapters_router(adapters,controls,controller))
    from services.api.robot_library import robot_library_router
    app.include_router(robot_library_router(store,adapters,controls,controller))
    app.include_router(configuration_router(store,controller,controls))
    app.include_router(llm_router(controller.llm,controller,controls))
    app.include_router(model_library_router(store,controller,controls))
    app.state.llm = controller.llm
    app.state.controls = controls
    app.state.adapters = adapters
    from services.api.business import business_router
    from services.api.rooms import rooms_router
    app.include_router(business_router(store,controller))
    app.include_router(rooms_router(store,controller,controls))

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        # Bind loopback only; reject browser requests from other origins and DNS-rebinding hosts.
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Local runtime only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in {"http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://localhost:5174", "http://127.0.0.1:8765", "http://localhost:5173", "http://localhost:8765"}:
            return JSONResponse({"detail": "Untrusted browser origin"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(FileNotFoundError)
    async def not_found(request, error):
        return JSONResponse({"detail": "Resource not found"}, status_code=404)

    @app.exception_handler(WorkerUnavailable)
    async def worker_failure(request, error):
        return JSONResponse({"detail":str(error)},status_code=502)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "0.4.0", "instance_id":os.getenv("ROBOT_IDE_INSTANCE_ID"), "provider": get_provider(controller.llm).name,
                "simulation": "Local kinematic preview", "hardware_enabled": False,
                "cloud_session":os.getenv('ROBOT_IDE_DEPLOYMENT')=='cloud',
                "isaac_sim_connected": any(s.remote is not None for s in controller.sessions.values())}

    @app.post('/api/session/activity')
    async def session_activity():
        if os.getenv('ROBOT_IDE_DEPLOYMENT')=='cloud':
            from integrations.gcp.activity import touch
            touch('cloud-user')
        return {'acknowledged':True}

    @app.get("/api/registry")
    async def get_registry():
        return store.models()

    @app.get("/api/projects")
    async def projects():
        return store.list_projects()

    @app.post("/api/projects", status_code=201)
    async def create_project(data: ProjectRequest):
        if not data.name.strip():
            raise ValueError("Project name cannot be blank")
        return store.create_project(data.name.strip(), data.source)

    @app.get("/api/projects/{project_id}")
    async def project(project_id: str):
        from services.api.isaac import worker_configuration
        configured=store.load_project(project_id)[0].get('simulation',{}).get('adapter')=='isaac_sim' and (controller.gpu.enabled() or worker_configuration(store)['deployment']=='local') and project_id not in controller.sessions
        if project_id in controller.offline or configured:
            session,states = controller.offline.get(project_id) or controller.configured_preview(project_id)
            project,instances,models,_ = store.load_project(project_id)
            primary = instances[0]['instance']['id']
            return {"robots":[{"instance":i,"model":m,"state":states[i['instance']['id']]} for i,m in zip(instances,models)],
                "adapter":session.backend,"worker":None,"environment_connected":False,"fingerprint":None,
                "project":project,"instance":instances[0],"model":models[0],"objects":session.objects,
                "state":states[primary],"held_object":session.held_object,"runs":store.list_runs(project_id),
                "plans":[],"plan_definitions":[d for d in store.list_definitions(project_id) if not store.definition_archived(project_id,d.id)],"active_run":None}
        project, instance, model, session, state = await controller.context(project_id)
        states = await controller.states(session)
        return {"robots":[{"instance":session.instances[rid],"model":session.models[rid],"state":states[rid]} for rid in session.adapters],
                "adapter":session.backend, "worker":session.remote.metadata if session.remote else None,
                "environment_connected":True,"fingerprint":fingerprint(await controller.snapshot(project_id)),
                "project": project, "instance": instance, "model": model, "objects": session.objects,
                "state": state, "held_object": session.held_object, "runs": store.list_runs(project_id),
                "plans": [{"id": p.id, "description": p.task.description, "valid": p.valid} for p in store.list_plans(project_id)],
                "plan_definitions": [d for d in store.list_definitions(project_id) if not store.definition_archived(project_id,d.id)],
                "active_run": controller.leases.get(project_id)}

    @app.post("/api/projects/{project_id}/plans", status_code=201)
    async def plan(project_id: str, data: PlanRequest):
        controller.ensure_idle(project_id)
        provider = get_provider(controller.llm)
        project, instance, model, session, state = await controller.context(project_id,data.robot_id)
        if any(session.held_objects.values()):
            raise ValueError("A previous run was interrupted while holding an object. Reset the preview scene first.")
        try:
            intent = await provider.interpret(data.prompt, session.objects)
        except (httpx.HTTPError, KeyError, TypeError) as error:
            raise HTTPException(502, "AI provider request failed. Check AI_BASE_URL, AI_MODEL and AI_API_KEY; no plan was executed.") from error
        controller.ensure_idle(project_id)
        # Provider requests can take seconds; capture fresh state after inference.
        project, instance, model, session, state = await controller.context(project_id,data.robot_id)
        snapshot = await controller.snapshot(project_id)
        generated = build_plan(project_id, data.prompt, intent, provider.name, model, instance, session.objects,
                               state.positions, fingerprint(snapshot))
        generated.adapter = session.backend
        if session.remote:
            for check in generated.checks:
                if check.id == "scope":
                    check.message = "Isaac Sim executes contact physics from the deployed USD cell. Planning checks are sampled and do not constitute continuous collision or hardware safety certification."
        states = await controller.states(session)
        generated.frames = controller.cell_frames(generated,states)
        from services.planning.workflow import validate_cell
        from shared.models.domain import Check
        try:
            validate_cell(generated.frames,session.models,session.objects)
        except ValueError as error:
            generated.valid = False
            generated.checks.append(Check(id="cell",label="Inter-robot proximity",status="failed",message=str(error)))
        store.save_plan(generated, snapshot)
        return generated

    @app.get("/api/projects/{project_id}/plans/{plan_id}")
    async def get_plan(project_id: str, plan_id: str):
        return store.get_plan(project_id, plan_id)

    @app.post("/api/projects/{project_id}/plans/{plan_id}/simulate", status_code=202)
    async def simulate(project_id: str, plan_id: str, data: ExecuteRequest):
        if data.mode != "simulation":
            raise HTTPException(409, "Physical execution is unavailable. A configuration flag cannot enable hardware control.")
        project = store.load_project(project_id)[0]
        selected = project.get("simulation",{}).get("adapter","mock")
        if data.adapter and data.adapter != selected:
            raise HTTPException(409,"Select and connect the simulation backend before generating a plan")
        return await controller.execute_registered_plan(plan_id, data.fingerprint, project_id,data.adapter)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        return controller.runs.get(run_id) or store.get_run(run_id)

    @app.post("/api/runs/{run_id}/stop")
    async def stop(run_id: str):
        return controller.stop(run_id)

    @app.post("/api/projects/{project_id}/sync")
    async def sync(project_id: str,robot_id: str | None = None):
        *_, state = await controller.context(project_id,robot_id)
        return state

    @app.post("/api/projects/{project_id}/reset")
    async def reset(project_id: str):
        await controller.reset(project_id)
        return {"status": "reset", "scope": "simulation_only"}

    @app.put("/api/projects/{project_id}/initial")
    async def save_initial(project_id: str, data: InitialRequest):
        controller.ensure_idle(project_id)
        project, instance, model, _, state = await controller.context(project_id,data.robot_id)
        validate_positions(model, data.positions)
        instance["initial_configuration"]["actuator_positions"] = data.positions
        path = next(store.project_folder(project_id)/relative for relative in project["robots"] if yaml.safe_load((store.project_folder(project_id)/relative).read_text())["instance"]["id"] == instance["instance"]["id"])
        temp = path.with_suffix(".tmp")
        temp.write_text(yaml.safe_dump(instance, sort_keys=False))
        temp.replace(path)
        return {"instance": instance, "actual_state": state}

    @app.put("/api/projects/{project_id}/world")
    async def save_world(project_id: str, data: WorldRequest):
        controller.ensure_idle(project_id)
        if len({o.id for o in data.objects}) != len(data.objects):
            raise ValueError("Duplicate world object IDs")
        if any(getattr(o.size, a) <= 0 for o in data.objects for a in ("x", "y", "z")):
            raise ValueError("Object dimensions must be positive")
        project, _, _, session, _ = await controller.context(project_id)
        if any(session.held_objects.values()):
            raise ValueError("Reset the preview before editing a scene with a held object")
        validate_asset_refs(store,project_id,data.objects)
        from services.execution.resources import environment_resource
        import uuid
        owner='scene-edit:'+uuid.uuid4().hex
        controller.resources.acquire([environment_resource(project_id,session.backend)],owner)
        try:
            if session.remote:
                observed=await session.remote.sync_objects(data.objects)
                session.objects=observed.objects
            path = store.project_folder(project_id) / project["environment"]
            temp = path.with_suffix(".tmp")
            temp.write_text(yaml.safe_dump({"frame": "world", "units": "m", "objects": [o.model_dump() for o in data.objects]}, sort_keys=False))
            temp.replace(path)
            if not session.remote:session.objects = data.objects
            await controller.persist_state(project_id)
            return {"objects": session.objects}
        finally:
            controller.resources.release(owner)

    @app.post("/api/projects/{project_id}/workflows/plans",status_code=201)
    async def workflow(project_id:str,data:WorkflowRequest):
        controller.ensure_idle(project_id)
        provider = get_provider(controller.llm)
        *_,session,_ = await controller.context(project_id)
        if any(session.held_objects.values()):
            raise ValueError("Reset the interrupted grasp before replanning")
        intents = {a.id:await provider.interpret(a.prompt,session.objects) for a in data.tasks}
        controller.ensure_idle(project_id)
        snapshot = await controller.snapshot(project_id)
        states = await controller.states(session)
        plan = build_workflow(project_id,data.tasks,intents,provider.name,list(session.instances.values()),session.models,session.objects,states,fingerprint(snapshot),session.backend)
        store.save_plan(plan,snapshot)
        return plan

    @app.put("/api/projects/{project_id}/simulation")
    async def simulation_backend(project_id:str,data:SimulationRequest):
        return await controller.switch_backend(project_id,data.adapter)

    @app.post("/api/projects/{project_id}/disconnect")
    async def disconnect(project_id:str):
        controller.ensure_idle(project_id)
        if project_id in controller.offline:
            return {"disconnected":True}
        *_,session,_ = await controller.context(project_id)
        states = await controller.states(session)
        if not session.remote:
            await controller.persist_state(project_id)
        await controller.disconnect(project_id)
        controller.offline[project_id] = (session,{rid:s.model_copy(update={'connected':False}) for rid,s in states.items()})
        return {"disconnected":True}

    @app.post("/api/projects/{project_id}/robots",status_code=201)
    async def add_robot(project_id:str,data:RobotRequest):
        import copy
        from services.validation.registry import load_instance, load_model, read_yaml
        controller.ensure_idle(project_id)
        project,instances,models,_ = store.load_project(project_id)
        if project.get("simulation",{}).get("adapter","mock") != "mock":
            raise ValueError("Switch to local preview before editing the robot registry; the GPU cell requires a matching deployed manifest")
        if len(instances)>=8 or data.id in {i["instance"]["id"] for i in instances}:
            raise ValueError("Robot ID already exists or the eight-robot limit was reached")
        selected_model = load_model(store.model_folder(data.model_id or models[0]['robot']['id']))
        instance = load_instance(store.model_folder(selected_model['robot']['id'])/'instances/instance.yaml',selected_model)
        if data.initial_positions is not None:
            validate_positions(selected_model,data.initial_positions)
            instance['initial_configuration']['actuator_positions'] = data.initial_positions
        from services.api.robot_library import resolve_binding
        instance['control_adapter']=resolve_binding(adapters,selected_model['robot']['id'],data.adapter_id,data.category)
        instance["instance"] = {"id":data.id,"name":data.name}
        instance["base_pose"] = data.base_pose
        relative = f"robots/{data.id}/instance.yaml"
        path = store.project_folder(project_id)/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(yaml.safe_dump(instance,sort_keys=False))
        try:
            load_instance(path,selected_model)
        except BaseException:
            path.unlink()
            raise
        previous_session = controller.sessions.get(project_id)
        if previous_session and any(previous_session.held_objects.values()):
            path.unlink(missing_ok=True)
            raise ValueError("Reset the interrupted grasp before adding robot instances")
        previous_states = await controller.states(previous_session) if previous_session else {}
        previous_objects = previous_session.objects if previous_session else None
        await controller.persist_state(project_id)
        await controller.disconnect(project_id)
        project["robots"].append(relative)
        (store.project_folder(project_id)/"project.yaml").write_text(yaml.safe_dump(project,sort_keys=False))
        # Initialize the expanded preview deliberately; previous configurations remain saved.
        *_,expanded_session,_ = await controller.context(project_id)
        for rid,state in previous_states.items():
            await expanded_session.adapters[rid].command(state.positions)
            await expanded_session.adapters[rid].request_stop()
        if previous_objects is not None:
            expanded_session.objects = previous_objects
        await controller.persist_state(project_id)
        return {"instance":instance}

    business_dist=REPOSITORY_ROOT/'BUSINESS_APP/dist'
    if business_dist.exists():app.mount('/business',StaticFiles(directory=business_dist,html=True),name='business')
    dist = REPOSITORY_ROOT / "SERVER_CLIENT/client/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="desktop")
    return app


app = create_app()
