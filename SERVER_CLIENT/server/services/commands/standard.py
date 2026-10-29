"""Validate a standardized command and resolve it to canonical joint targets.

Only MOVE_END_EFFECTOR invokes IK. Adapters receive the resulting targets through
existing joint mappings/transports; no LLM text or generated source is executed.
"""
from shared.models.command import StandardCommand
from services.planning.kinematics import inverse, supports_model
from services.validation.registry import validate_positions


def components(model):
    configured=dict(model['capabilities'].get('components',{}))
    if 'gripper' in model['actuators']['actuators'] and model['kinematics']['solver']=='analytic_yaw_two_link_v1':
        configured.setdefault(model['capabilities']['end_effector'],{'actuator':'gripper','closed':0.,'open':.08})
    return configured


def effectors(model):
    if model['kinematics']['solver']=='serial_chain_dls_v1':return list(model['kinematics'].get('end_effectors',{}))
    if supports_model(model):return [model['capabilities']['end_effector']]
    return []


def capability_description(model):
    return {'robot_id':model['robot']['id'],'description':model['robot']['description'],
        'actuators':model['actuators']['actuators'],'components':components(model),
        'end_effectors':effectors(model),'kinematics':model['kinematics'],
        'constraints':model['capabilities'], 'control_schemes':model['control_schemes'],
        'standard_commands':StandardCommand.model_json_schema(),
        'frames':[model['kinematics']['world_frame']],'adapter_execution':'simulation_only'}


def resolve_command(model,current,command):
    c=command if isinstance(command,StandardCommand) else StandardCommand.model_validate(command)
    q=dict(current)
    if c.type=='SET_ACTUATOR':
        spec=model['actuators']['actuators'].get(c.target)
        if spec is None:raise ValueError(f'Unknown actuator: {c.target}')
        if c.unit!=spec['unit']:raise ValueError(f'{c.target}: expected unit {spec["unit"]}')
        q[c.target]=c.value
    elif c.type=='SET_COMPONENT':
        spec=components(model).get(c.target)
        if spec is None:raise ValueError(f'Unknown controllable component: {c.target}')
        if c.unit!='percent' or not 0<=c.value<=100:raise ValueError('Component opening requires percent in [0,100]')
        q[spec['actuator']]=spec['closed']+(spec['open']-spec['closed'])*c.value/100
    else:
        if c.target not in effectors(model):raise ValueError(f'Unknown or unsupported end effector: {c.target}')
        if c.frame!=model['kinematics']['world_frame']:raise ValueError('Pose frame is not configured for this robot')
        if model['kinematics']['solver']=='serial_chain_dls_v1':
            from services.planning.serial_ik import inverse_pose
            q=inverse_pose(model,c.position,c.orientation_rpy,current,c.target)
        else:
            from shared.models.domain import Pose
            if c.orientation_rpy is not None:
                raise ValueError('Demo analytic solver only supports its fixed tool orientation; configure serial_chain_dls_v1 for pose IK')
            q=inverse(model,Pose(**dict(zip(('x','y','z'),c.position))),current['gripper'])
    validate_positions(model,q)
    return q
