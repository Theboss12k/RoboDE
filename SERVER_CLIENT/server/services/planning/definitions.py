"""Compile editable atomic tasks into immutable synchronized simulation revisions."""
import math
import re
import uuid
from pprint import pformat
from shared.models.domain import Check, Frame, Plan, TaskSpec, TaskStep
from services.task_engine.graph import topological_order
from services.planning.kinematics import forward, inverse, require_solver, supports_model
from services.planning.workflow import validate_cell
from services.validation.registry import validate_positions
from services.validation.trajectory import validate_trajectory
from services.world_model.world import object_map, contained


def validate_definition(definition, robot_ids):
    if len(definition.tasks)>144:raise ValueError('A plan supports at most 144 tasks')
    if not definition.name.strip():
        raise ValueError("Plan name cannot be blank")
    steps = []
    for task in definition.tasks:
        if not task.name.strip() or (task.operation != 'llm' and task.robot_id not in robot_ids):
            raise ValueError(f"{task.id}: name and explicit project robot assignment are required")
        if task.operation == 'llm':
            if task.robot_id or not task.llm_input.strip() or any(v is not None for v in (task.target,task.joint_positions,task.object_id,task.target_id)):
                raise ValueError(f'{task.id}: LLM tasks require input, no robot assignment and no motion/object parameters')
        if task.operation=='command':
            if task.command is None or any(v is not None for v in (task.target,task.joint_positions)):
                raise ValueError(f'{task.id}: standardized tasks require a command and no legacy motion parameters')
        elif task.command is not None:
            raise ValueError(f'{task.id}: command is only allowed for a standardized task')
        if task.target is not None and task.joint_positions is not None:
            raise ValueError(f"{task.id}: choose a Cartesian target or joint positions")
        if task.operation != 'move' and (task.target is not None or task.joint_positions is not None):
            raise ValueError(f"{task.id}: only Move accepts motion parameters")
        steps.append(TaskStep(id=task.id,label=task.name,operation=task.operation,dependencies=task.dependencies,implementation='atomic',robot_id=task.robot_id))
    order = topological_order(steps)
    ancestors = {}
    by_id = {t.id:t for t in definition.tasks}
    for step in order:
        ancestors[step.id] = set(step.dependencies)
        for dependency in step.dependencies:
            ancestors[step.id].update(ancestors[dependency])
        for reference in re.findall(r'\{\{tasks\.([a-zA-Z0-9_:-]+)\.answer\}\}',by_id[step.id].llm_input):
            if reference not in ancestors[step.id] or by_id[reference].operation != 'llm':
                raise ValueError(f'{step.id}: answer reference {reference} must be an LLM dependency')


def compile_definition(definition, instances, models, objects, states, fingerprint, adapter):
    validate_definition(definition, set(instances))
    if not definition.tasks:
        raise ValueError("Add at least one task before compiling")
    has_motion = any(t.operation != "llm" for t in definition.tasks)
    by_id = {t.id:t.model_copy(deep=True) for t in definition.tasks}
    steps = [TaskStep(id=t.id,label=t.name,operation=t.operation,implementation='services.planning.definitions',dependencies=t.dependencies,robot_id=t.robot_id) for t in definition.tasks]
    order = topological_order(steps)
    # Deterministically serialize shared devices, objects and destination volumes.
    previous = {}
    for step in order:
        task = by_id[step.id]
        robot_resources = [f'robot:{rid}' for rid in instances] if task.operation == 'llm' else [f'robot:{task.robot_id}']
        for resource in [*robot_resources, *[f'world:{v}' for v in (task.object_id,task.target_id) if v]]:
            if resource in previous and previous[resource] not in task.dependencies:
                task.dependencies.append(previous[resource])
            previous[resource] = task.id
    tasks = [by_id[s.id] for s in topological_order([s.model_copy(update={'dependencies':by_id[s.id].dependencies}) for s in order])]
    predicted = {rid:dict(state.positions) for rid,state in states.items()}
    initial_poses = object_map(objects)
    poses = {key:value.model_copy() for key,value in initial_poses.items()}
    held = dict.fromkeys(instances)
    local, schedule, changed = {}, {}, {}
    checks = [Check(id='graph',label='Task assignments and dependencies',status='passed',message='Explicit project robot assignments; acyclic dependencies; shared robots, objects and regions serialized.')]
    known_objects = {o.id:o for o in objects}
    for task in tasks:
        start = max((schedule[d]['end_tick'] for d in task.dependencies),default=-1)+1
        if task.operation == 'llm':
            local[task.id] = [Frame(time=0,step_id=task.id,positions={},objects={})]
            changed[task.id] = set()
            schedule[task.id] = {'start_tick':start,'end_tick':start+1,'start':start/30,'end':(start+1)/30}
            continue
        rid = task.robot_id
        model, current = models[rid], predicted[rid]
        for key, kind in ((task.object_id,'object'),(task.target_id,'obstacle' if task.placement=='on_surface' else 'region')):
            if key and (key not in known_objects or known_objects[key].kind != kind):
                raise ValueError(f'{task.name}: unknown {kind}: {key}')
        if task.operation in {'grasp','release'} and not task.object_id:
            raise ValueError(f'{task.name}: select an object')
        target = dict(current)
        carrying = held[rid]
        changed[task.id] = {carrying} if carrying else set()
        if task.operation == 'command':
            from services.commands.standard import resolve_command
            target=resolve_command(model,current,task.command)
        elif task.operation == 'move':
            if task.target is None and task.joint_positions is None:require_solver(model)
            target = (dict(task.joint_positions) if task.joint_positions is not None else
                      inverse(model,task.target,current.get('gripper',0.08)) if task.target is not None else
                      dict(instances[rid]['initial_configuration']['actuator_positions']))
            validate_positions(model,target)
        elif task.operation == 'grasp':
            if 'pick_place' not in model['capabilities']['operations']:raise ValueError('Robot does not support object manipulation')
            if model['kinematics']['solver']!='analytic_yaw_two_link_v1':raise ValueError('Object grasp simulation requires a configured contact/grasp implementation for this model')
            item = known_objects[task.object_id]
            if held[rid] or task.object_id in held.values():
                raise ValueError(f'{task.name}: object or gripper already held')
            if item.mass_kg > model['capabilities']['payload_kg']:
                raise ValueError(f'{task.name}: object exceeds payload')
            if math.dist(tuple(forward(model,current).model_dump().values()),tuple(poses[item.id].model_dump().values())) > .012:
                raise ValueError(f'{task.name}: object is outside grasp tolerance')
            target['gripper'] = min(.06,item.size.x*.7)
            changed[task.id].add(item.id)
        elif task.operation == 'release':
            if model['kinematics']['solver']!='analytic_yaw_two_link_v1':raise ValueError('Object release simulation requires a configured contact/grasp implementation for this model')
            if carrying != task.object_id:
                raise ValueError(f'{task.name}: this robot is not holding the selected object')
            target['gripper'] = .08
        elif task.operation == 'verify':
            if task.object_id:
                if not task.target_id:
                    raise ValueError(f'{task.name}: select a destination region for placement verification')
                item = known_objects[task.object_id].model_copy(update={'position':poses[task.object_id]})
                from services.world_model.world import placement_satisfied
                if not placement_satisfied(item,known_objects[task.target_id],task.placement) or task.object_id in held.values():
                    raise ValueError(f'{task.name}: predicted placement postcondition failed')
        duration = .35
        for key, value in current.items():
            delta = abs(target[key]-value)
            limits = model['actuators']['actuators'][key]
            duration = max(duration,1.95*delta/limits['velocity'],math.sqrt(6.2*delta/limits['acceleration']))
        count = max(12,math.ceil(duration*30))
        start = max((schedule[d]['end_tick'] for d in task.dependencies),default=-1)+1
        frames = []
        for n in range(count+1):
            t = n/count
            blend = 10*t**3-15*t**4+6*t**5
            q = {key:current[key]+(target[key]-current[key])*blend for key in current}
            if carrying:
                poses[carrying] = forward(model,q)
            if n == count:
                if task.operation=='command' and carrying and model['kinematics']['solver']=='analytic_yaw_two_link_v1' and target['gripper']>=.075:
                    held[rid]=None
                if task.operation == 'grasp':
                    held[rid] = task.object_id
                elif task.operation == 'release':
                    held[rid] = None
            frames.append(Frame(time=n/30,step_id=task.id,positions=q,objects={k:v.model_copy() for k,v in poses.items()},held_object=held[rid]))
        predicted[rid] = target
        local[task.id] = frames
        schedule[task.id] = {'start_tick':start,'end_tick':start+count,'start':start/30,'end':(start+count)/30}
    frames = []
    primary = next(iter(instances))
    for tick in range(int(max(s['end_tick'] for s in schedule.values()))+1):
        q = {rid:dict(s.positions) for rid,s in states.items()}
        world = {k:v.model_copy() for k,v in initial_poses.items()}
        holding, active = dict.fromkeys(instances), {}
        for task in tasks:
            entry = schedule[task.id]
            if tick < entry['start_tick']:
                continue
            f = local[task.id][min(tick-int(entry['start_tick']),len(local[task.id])-1)]
            if task.operation != 'llm':
                q[task.robot_id] = f.positions
                holding[task.robot_id] = f.held_object
            for key in changed[task.id]:
                world[key] = f.objects[key]
            if tick <= entry['end_tick']:
                active[task.robot_id or f'llm:{task.id}'] = task.id
        frames.append(Frame(time=round(tick/30,6),step_id=next(iter(active.values()),tasks[-1].id),positions=q[primary],objects=world,
                            robot_positions=q,held_objects=holding,held_object=holding[primary],active_steps=active))
    try:
        for rid,model in (models.items() if has_motion else []):
            validate_trajectory(model,[f.model_copy(update={'positions':f.robot_positions[rid]}) for f in frames],objects)
        if has_motion:
            validate_cell(frames,models,objects)
            if any(not supports_model(m) for m in models.values()):
                checks.append(Check(id='geometry_scope',label='Geometry unavailable',status='warning',message='Direct joint/component tasks checked against units and joint rates only; link geometry and IK unavailable for this model.'))
        checks.append(Check(id='motion',label='Motion and cell geometry',status='passed',message='Joint position, velocity, acceleration, sampled links, carried objects and inter-robot proximity checked.' if has_motion else 'LLM-only plan: no joint commands or physics steps.'))
    except ValueError as error:
        checks.append(Check(id='motion',label='Motion and cell geometry',status='failed',message=str(error)))
    checks.append(Check(id='scope',label='Simulation scope',status='warning',message='Built-in simulation uses ideal grasps. Isaac Sim requires matching deployed assets. Sampled checks do not certify continuous collision avoidance or hardware safety.'))
    revision_id = uuid.uuid4().hex[:12]
    trace = [TaskStep(id=t.id,label=t.name,operation=t.operation,robot_id=t.robot_id,target=t.target,object_id=t.object_id,
                     dependencies=t.dependencies,implementation='services.execution.controller.SimulationController.verify_atomic') for t in tasks]
    spec = TaskSpec(id=definition.id,description=definition.goal or definition.name,robot_id=primary,template='multi_robot',
                    required_capabilities=[],success_condition='Every atomic task verifies its declared result',steps=trace,provider='Atomic task compiler')
    code = ('# Immutable compiled plan revision. Manifest is data, never evaluated.\n'
            f'PLAN_ID = {revision_id!r}\nDEFINITION_ID = {definition.id!r}\nEXPECTED_FINGERPRINT = {fingerprint!r}\n'
            f'TASKS = {pformat([t.model_dump(mode="json", exclude={"llm_system_prompt"}) for t in tasks],width=90)}\n\n'
            'async def run(controller):\n    return await controller.execute_registered_plan(PLAN_ID, EXPECTED_FINGERPRINT)\n')
    return Plan(id=revision_id,project_id=definition.project_id,definition_id=definition.id,definition_version=definition.version,
                atomic_tasks=tasks,task_schedule=schedule,task=spec,checks=checks,frames=frames,code=code,duration=max(frames[-1].time,1/30),
                valid=all(c.status!='failed' for c in checks),fingerprint=fingerprint,adapter=adapter)
