"""Compile explicitly assigned tasks into one sampled, dependency-aware cell timeline."""
import math
import uuid
from shared.models.domain import Check, Contract, Frame, Plan, TaskSpec, TaskStep, WorkflowTask
from pydantic import Field
from services.planning.planner import build_plan
from services.planning.kinematics import link_points, supports_model, link_segments
from services.task_engine.graph import topological_order
from services.world_model.world import object_map


class Assignment(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    robot_id: str
    prompt: str = Field(min_length=1, max_length=4000)
    dependencies: list[str] = Field(default_factory=list)


def ordered_assignments(assignments):
    if not assignments or len(assignments) > 16:
        raise ValueError("A workflow requires 1 to 16 assigned tasks")
    steps = [TaskStep(id=a.id, label=a.prompt, operation="move", implementation="workflow", dependencies=a.dependencies) for a in assignments]
    order = topological_order(steps)
    by_id = {a.id: a.model_copy(deep=True) for a in assignments}
    # Same-robot tasks serialize in deterministic topological order.
    previous = {}
    for step in order:
        item = by_id[step.id]
        if item.robot_id in previous and previous[item.robot_id] not in item.dependencies:
            item.dependencies.append(previous[item.robot_id])
        previous[item.robot_id] = item.id
    return [by_id[s.id] for s in order]


def distance_to_segment(point, a, b):
    ab = [y-x for x,y in zip(a,b)]
    length = sum(x*x for x in ab)
    t = max(0., min(1., sum((p-x)*d for p,x,d in zip(point,a,ab))/length)) if length else 0
    return math.dist(point, [x+t*d for x,d in zip(a,ab)])


def validate_cell(frames, models, objects):
    for frame in frames:
        points = {rid: link_points(models[rid], q) for rid,q in frame.robot_positions.items() if supports_model(models[rid])}
        segments={rid:link_segments(models[rid],frame.robot_positions[rid]) for rid in points}
        ids = list(points)
        for i, first in enumerate(ids):
            for second in ids[i+1:]:
                for a,b in segments[first]:
                    samples = max(2, math.ceil(math.dist(a,b)/.02))
                    for n in range(samples+1):
                        p = [x+(y-x)*n/samples for x,y in zip(a,b)]
                        if any(distance_to_segment(p,c,d) < .08 for c,d in segments[second]):
                            raise ValueError(f"Inter-robot proximity: {first}/{second} at {frame.time:.2f}s; separate bases or change the workflow")
        for owner, object_id in frame.held_objects.items():
            if not object_id:
                continue
            p = frame.objects[object_id]
            item = next(o for o in objects if o.id == object_id)
            for other in ids:
                if owner != other and any(distance_to_segment((p.x,p.y,p.z),a,b) < max(item.size.model_dump().values())/2+.04 for a,b in segments[other]):
                    raise ValueError(f"Carried object {object_id} approaches robot {other}")


def build_workflow(project_id, assignments, intents, provider, instances, models, objects, states, fingerprint, adapter="mock"):
    order = ordered_assignments(assignments)
    known = {i["instance"]["id"]:i for i in instances}
    predicted = {rid:dict(s.positions) for rid,s in states.items()}
    world = [o.model_copy(deep=True) for o in objects]
    compiled, ancestors, children = {}, {}, []
    checks, flat_steps = [], []
    for assignment in order:
        rid, key = assignment.robot_id, assignment.id
        if rid not in known:
            raise ValueError(f"Unknown robot instance: {rid}")
        parents = set(assignment.dependencies)
        ancestors[key] = parents | set().union(*(ancestors[d] for d in parents)) if parents else set()
        intent = intents[key]
        resources = {x for x in [intent.object_id,intent.target_id] if x}
        for previous in children:
            used = {x for x in [previous.task.object_id,previous.task.target_id] if x}
            if resources & used and previous.id not in ancestors[key]:
                raise ValueError(f"Tasks {previous.id} and {key} share an object or target. Add an explicit dependency.")
        child = build_plan(project_id,assignment.prompt,intent,provider,models[rid],known[rid],world,predicted[rid],fingerprint)
        checks.extend(c.model_copy(update={"id":f"{key}:{c.id}","label":f"{rid} / {c.label}"}) for c in child.checks if c.status != "warning")
        start = max((compiled[d]["end"] for d in assignment.dependencies), default=-1/30)+1/30
        start_tick = round(start*30)
        end_tick = start_tick+len(child.frames)-1
        compiled[key] = {"plan":child,"start":start_tick,"end":end_tick/30}
        for step in child.task.steps:
            dependencies = [f"{key}:{d}" for d in step.dependencies]
            if not dependencies:
                dependencies = [f"{d}:{compiled[d]['plan'].task.steps[-1].id}" for d in assignment.dependencies]
            flat_steps.append(step.model_copy(update={"id":f"{key}:{step.id}","dependencies":dependencies,"robot_id":rid}))
        children.append(WorkflowTask(id=key,robot_id=rid,dependencies=assignment.dependencies,start=start_tick/30,end=end_tick/30,
                                     task=child.task,final_positions=child.frames[-1].positions))
        predicted[rid] = child.frames[-1].positions
        if intent.object_id and intent.object_id in child.frames[-1].objects:
            next(o for o in world if o.id == intent.object_id).position = child.frames[-1].objects[intent.object_id]
    topological_order(flat_steps)
    ticks = round(max(c.end for c in children)*30)
    frames = []
    for tick in range(ticks+1):
        q = {rid:dict(s.positions) for rid,s in states.items()}
        poses, held, active = object_map(objects), {rid:None for rid in known}, {}
        for task in children:
            item = compiled[task.id]
            if tick < item["start"]:
                continue
            local = min(tick-item["start"],len(item["plan"].frames)-1)
            f = item["plan"].frames[local]
            q[task.robot_id] = f.positions
            held[task.robot_id] = f.held_object
            if task.task.object_id:
                poses[task.task.object_id] = f.objects[task.task.object_id]
            if tick <= round(task.end*30):
                active[task.robot_id] = f"{task.id}:{f.step_id}"
        first = instances[0]["instance"]["id"]
        frames.append(Frame(time=round(tick/30,6),step_id=next(iter(active.values()),flat_steps[-1].id),positions=q[first],objects=poses,
                            robot_positions=q,held_objects=held,active_steps=active,held_object=held[first]))
    try:
        validate_cell(frames,models,objects)
        checks.append(Check(id="cell",label="Inter-robot proximity",status="passed",message="Synchronized sampled link and carried-object separation checked for every robot, including idle robots."))
    except ValueError as error:
        checks.append(Check(id="cell",label="Inter-robot proximity",status="failed",message=str(error)))
    checks.extend([Check(id="assignments",label="Resources and dependencies",status="passed",message="Robot leases are serialized; shared objects and targets require explicit dependencies."),
                   Check(id="scope",label="Simulation scope",status="warning",message="Sampled geometry is not continuous collision certification. Local preview grasps are idealized; Isaac Sim uses measured physics observations.")])
    task = TaskSpec(id=uuid.uuid4().hex[:12],description="Multi-robot workflow",robot_id=first,template="multi_robot",required_capabilities=[],success_condition="Every assigned task verifies its own postconditions",steps=flat_steps,provider=provider)
    plan_id = uuid.uuid4().hex[:12]
    code = "# Coordinated simulation workflow; implementation: services/execution/controller.py\n"+f"# Assignments: {[(c.id,c.robot_id,c.dependencies) for c in children]!r}\n"
    code += f"PLAN_ID = {plan_id!r}\nEXPECTED_FINGERPRINT = {fingerprint!r}\n\nasync def run(controller):\n    return await controller.execute_registered_plan(PLAN_ID, EXPECTED_FINGERPRINT)\n"
    return Plan(id=plan_id,project_id=project_id,task=task,checks=checks,frames=frames,code=code,duration=ticks/30,
                valid=not any(c.status=="failed" for c in checks),fingerprint=fingerprint,adapter=adapter,workflow_tasks=children)
