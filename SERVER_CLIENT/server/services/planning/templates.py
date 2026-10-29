"""Offline examples and goal templates produce the same editable task contract as the LLM.

Bindings substitute exact declared values, never expressions or executable code.
Motion stays in StandardCommand; grasp/release/verify retain explicit task semantics.
"""
import copy
from shared.models.domain import TaskDefinition
from services.commands.standard import effectors
from services.planning.workflow import ordered_assignments
from services.validation.registry import ROOT, read_yaml, validate_positions


def bind(value, values):
    if isinstance(value,str) and value.startswith('$'):
        key=value[1:]
        if key not in values:raise ValueError(f'Unknown template binding: {key}')
        return copy.deepcopy(values[key])
    if isinstance(value,dict):return {k:bind(v,values) for k,v in value.items()}
    if isinstance(value,list):return [bind(v,values) for v in value]
    return value


def expand_template(template_id,model,instance,objects,object_id=None,target_id=None):
    if template_id not in {'pick_place','move_home'}:raise ValueError('Unsupported offline task template')
    template=read_yaml(ROOT/'task_library/manipulation'/f'{template_id}.yaml')
    if not set(template['required_capabilities']).issubset(model['capabilities']['operations']):
        raise ValueError('Robot does not declare the required template capabilities')
    values={};item=target=None
    if template_id=='pick_place':
        known={o.id:o for o in objects};item=known.get(object_id);target=known.get(target_id)
        if item is None or item.kind!='object' or target is None or target.kind!='region':
            raise ValueError('Pick/place requires a known object and destination region')
        if item.mass_kg>model['capabilities']['payload_kg']:raise ValueError('Object exceeds robot payload')
        if any(getattr(item.size,a)>=getattr(target.size,a) for a in ('x','y','z')):raise ValueError('Object does not fit inside the destination region')
        names=effectors(model)
        if model['kinematics']['solver']!='analytic_yaw_two_link_v1' or len(names)!=1:
            raise ValueError('This offline grasp template requires the supported demo contact/effector model')
        values={'end_effector':names[0],'world_frame':model['kinematics']['world_frame'],
            'clearance_z':max(item.position.z,target.position.z)+.18,
            'grasp_name':f'Grasp {item.name.lower()}' if item.id=='apple' else f'Grasp {item.name}',
            'transfer_name':f'Transfer to {target.name.lower()}' if target.id=='basket' else f'Transfer to {target.name}',
            **{f'object_{a}':getattr(item.position,a) for a in ('x','y','z')},
            **{f'target_{a}':getattr(target.position,a) for a in ('x','y','z')}}
    initial=instance['initial_configuration']['actuator_positions'];validate_positions(model,initial)
    tasks=[]
    for definition in template['tasks']:
        repeats=list(model['actuators']['actuators']) if definition.get('repeat')=='actuators' else [None]
        for actuator in repeats:
            local={**values}
            if actuator is not None:
                local.update(actuator=actuator,actuator_unit=model['actuators']['actuators'][actuator]['unit'],
                    initial_value=initial[actuator],home_task_id=f'home_{actuator}',home_task_name=f'Set {actuator} to initial position')
            data=bind({k:v for k,v in definition.items() if k!='repeat'},local)
            tasks.append(TaskDefinition(**data,robot_id=instance['instance']['id'],dependencies=[tasks[-1].id] if tasks else [],
                object_id=object_id,target_id=target_id))
    return tasks


def draft_template_tasks(assignments,intents,instances,models,objects):
    tasks=[];terminals={};world=[o.model_copy(deep=True) for o in objects]
    for goal in ordered_assignments(assignments):
        if goal.robot_id not in instances:raise ValueError(f'Unknown robot instance: {goal.robot_id}')
        intent=intents[goal.id]
        proposed=expand_template(intent.template,models[goal.robot_id],instances[goal.robot_id],world,intent.object_id,intent.target_id)
        mapping={t.id:f'{goal.id}:{t.id}' for t in proposed}
        for task in proposed:
            task.id=mapping[task.id]
            task.dependencies=[mapping[d] for d in task.dependencies] or [terminals[d] for d in goal.dependencies]
            tasks.append(TaskDefinition.model_validate(task.model_dump()))
        terminals[goal.id]=proposed[-1].id
        if intent.template=='pick_place':
            item=next(o for o in world if o.id==intent.object_id);target=next(o for o in world if o.id==intent.target_id)
            item.position=target.position.model_copy()
    return tasks
