"""Declarative adapter commands. No vendor source or user expressions are evaluated."""
import math
import re
from typing import Literal
from pydantic import Field, StrictFloat
from shared.models.domain import Contract
from services.validation.registry import validate_positions

IDENTIFIER = r'^[a-z][a-z0-9_]{0,59}$'
REFERENCE = re.compile(r'^\$([a-z][a-z0-9_]{0,59})$')

class CommandParameter(Contract):
    min: StrictFloat
    max: StrictFloat
    default: StrictFloat
    unit: str = Field(default='',max_length=24)
    description: str = Field(default='',max_length=500)

class CommandStep(Contract):
    operation: Literal['move','increment','gripper','wait','feedback','stop']
    values: dict[str,StrictFloat | str] = Field(default_factory=dict,max_length=32)
    duration: float = Field(default=.5,ge=.05,le=10)

class AdapterCommand(Contract):
    id: str = Field(pattern=IDENTIFIER)
    name: str = Field(min_length=1,max_length=100)
    description: str = Field(default='',max_length=1200)
    vendor_command: str = Field(default='',max_length=500)
    documentation_quote: str = Field(default='',max_length=1000)
    parameters: dict[str,CommandParameter] = Field(default_factory=dict,max_length=32)
    steps: list[CommandStep] = Field(default_factory=list,max_length=16)
    simulation_supported: bool = True
    unsupported_reason: str = Field(default='',max_length=1000)


def validate_catalog(commands, controls, initial):
    if not commands or len(commands)>64 or len({c.id for c in commands})!=len(commands):
        raise ValueError('Define 1–64 commands with unique IDs')
    for command in commands:
        if not command.name.strip():
            raise ValueError('Command name cannot be blank')
        if not command.simulation_supported:
            if command.steps or not command.unsupported_reason.strip():
                raise ValueError(f'{command.id}: unavailable commands require a reason and no executable recipe')
            continue
        if not command.steps:
            raise ValueError(f'{command.id}: define a simulator recipe')
        for key,p in command.parameters.items():
            if not re.fullmatch(IDENTIFIER,key) or not p.min<=p.default<=p.max:
                raise ValueError(f'{command.id}: parameter names, ranges and defaults must be valid')
        used=set()
        for step in command.steps:
            motion=step.operation in {'move','increment','gripper'}
            if motion and (not step.values or not set(step.values).issubset(controls)):
                raise ValueError(f'{command.id}: motion must reference registered actuators')
            if step.operation=='gripper' and set(step.values)!={'gripper'}:
                raise ValueError(f'{command.id}: gripper requires a configured gripper actuator')
            if not motion and step.values:
                raise ValueError(f'{command.id}: {step.operation} cannot contain joint values')
            for key,value in step.values.items():
                if isinstance(value,str):
                    reference=REFERENCE.fullmatch(value)
                    if not reference or reference[1] not in command.parameters:
                        raise ValueError(f'{command.id}: use a number or $parameter reference')
                    parameter=command.parameters[reference[1]]
                    if parameter.unit and parameter.unit!=controls[key]['unit']:
                        raise ValueError(f'{command.id}: {key} parameters use {controls[key]["unit"]}; remote conversion belongs to the adapter')
                    used.add(reference[1])
        if used!=set(command.parameters):
            raise ValueError(f'{command.id}: every parameter must be used by the simulator recipe')
        compile_recipe(command,{k:p.default for k,p in command.parameters.items()},initial,controls)
    return commands


def compile_recipe(command, arguments, initial, controls):
    if not command.simulation_supported:
        raise ValueError(command.unsupported_reason or 'Command has no simulator implementation')
    if set(arguments)!=set(command.parameters):
        raise ValueError('Supply every declared command parameter exactly once')
    for key,value in arguments.items():
        p=command.parameters[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not p.min<=value<=p.max:
            raise ValueError(f'{key}: parameter must be within [{p.min}, {p.max}] {p.unit}')
    model={'actuators':{'actuators':controls}}
    q=dict(initial);validate_positions(model,q)
    frames=[];elapsed=0.
    for index,step in enumerate(command.steps):
        if step.operation not in {'move','increment','gripper'}:
            duration=step.duration if step.operation=='wait' else 0.
            frames.append({'operation':step.operation,'positions':dict(q),'duration':duration,'step_index':index})
            elapsed+=duration
        else:
            target=dict(q)
            for key,value in step.values.items():
                value=arguments[value[1:]] if isinstance(value,str) else value
                target[key]=(target[key]+value if step.operation=='increment' else value)
            validate_positions(model,target)
            duration=step.duration
            for key,a in controls.items():
                delta=abs(target[key]-q[key])
                duration=max(duration,1.95*delta/a['velocity'],math.sqrt(6.2*delta/a['acceleration']))
            count=max(2,math.ceil(duration*30))
            if count>1800:
                raise ValueError('Command motion exceeds the 60-second simulator test limit')
            for n in range(1,count+1):
                t=n/count;blend=10*t**3-15*t**4+6*t**5
                frames.append({'operation':'command','positions':{k:q[k]+(target[k]-q[k])*blend for k in q},'duration':1/30,'step_index':index})
            q=target;elapsed+=count/30
        if elapsed>60 or len(frames)>1800:
            raise ValueError('Command exceeds the 60-second simulator test limit')
    return frames


def default_commands(controls, initial):
    names={}
    for index,key in enumerate(controls):
        name=key if re.fullmatch(IDENTIFIER,key) else f'joint_{index+1}'
        while name in names.values(): name='p_'+name
        names[key]=name
    result=[AdapterCommand(id='set_joints',name='Set joint positions',description='Move each joint to its setpoint in canonical model units.',
        parameters={names[k]:CommandParameter(min=a['min'],max=a['max'],default=initial[k],unit=a['unit']) for k,a in controls.items()},
        steps=[CommandStep(operation='move',values={k:'$'+names[k] for k in controls})]),
        AdapterCommand(id='initial_pose',name='Return to initial pose',steps=[CommandStep(operation='move',values=initial)]),
        AdapterCommand(id='feedback',name='Read feedback',steps=[CommandStep(operation='feedback')]),
        AdapterCommand(id='stop',name='Stop',steps=[CommandStep(operation='stop')])]
    for index,(key,a) in enumerate(controls.items()):
        span=min((a['max']-a['min'])/4,.15 if a['unit']=='rad' else .01)
        # Default zero is valid even when the saved pose is at a joint limit.
        result.append(AdapterCommand(id=f'jog_{index+1}_'+re.sub(r'[^a-z0-9_]','_',key.lower())[:40],name='Jog '+key,parameters={'delta':CommandParameter(min=-span,max=span,default=0.,unit=a['unit'])},steps=[CommandStep(operation='increment',values={key:'$delta'})]))
    if 'gripper' in controls:
        for name,endpoint in [('open','max'),('close','min')]:
            result.append(AdapterCommand(id=name+'_gripper',name=name.title()+' gripper',steps=[CommandStep(operation='gripper',values={'gripper':controls['gripper'][endpoint]})]))
    return result
