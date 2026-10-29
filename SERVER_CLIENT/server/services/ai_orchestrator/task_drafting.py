"""Capability-aware LLM decomposition into reviewable task data."""
import json
from shared.models.domain import Contract,TaskDefinition
from pydantic import Field, ValidationError
from services.commands.standard import capability_description,resolve_command
from services.planning.definitions import validate_definition
from services.ai_orchestrator.llm import json_answer
from services.ai_orchestrator.goal_constraints import relative_object_lift


class TaskProposal(Contract):
    tasks:list[TaskDefinition]=Field(min_length=1,max_length=72)


def drafting_schema(model,robot_id):
    """Describe just robot drafting, with required fields per command variant.

    Runtime TaskDefinition validation remains authoritative. Removing unrelated
    LLM-task fields and duplicate schemas keeps local models inside their context.
    """
    from services.commands.standard import components,effectors
    number={'type':'number'}
    vector={'type':'array','items':number,'minItems':3,'maxItems':3}
    def command(kind,properties,required):
        return {'type':'object','additionalProperties':False,'properties':{'type':{'const':kind},**properties},'required':['type',*required]}
    commands={'oneOf':[
        command('SET_ACTUATOR',{'target':{'enum':list(model['actuators']['actuators'])},'value':number,'unit':{'enum':['rad','m']}},['target','value','unit']),
        command('SET_COMPONENT',{'target':{'enum':list(components(model))},'value':{'type':'number','minimum':0,'maximum':100},'unit':{'const':'percent'}},['target','value','unit']),
        command('MOVE_END_EFFECTOR',{'target':{'enum':effectors(model)},'position':vector,'position_unit':{'const':'m'},
            'frame':{'const':model['kinematics']['world_frame']},'orientation_rpy':vector,'orientation_unit':{'const':'rad'}},['target','position','position_unit','frame'])]}
    task={'type':'object','additionalProperties':False,'properties':{
        'id':{'type':'string'},'name':{'type':'string'},'robot_id':{'const':robot_id},
        'operation':{'enum':['command','grasp','release','verify']},'dependencies':{'type':'array','items':{'type':'string'}},
        'command':commands,'object_id':{'type':'string'},'target_id':{'type':'string'},'placement':{'enum':['inside','on_surface']}},
        'required':['id','name','robot_id','operation','dependencies']}
    return {'type':'object','additionalProperties':False,'properties':{'tasks':{'type':'array','minItems':1,'maxItems':72,'items':task}},'required':['tasks']}


def system_prompt(model,robot_id,objects,positions,goal=''):
    description=capability_description(model)
    description.pop('standard_commands',None)  # Defined once, with conditional required fields, below.
    return ('Decompose the user goal into simple executable TASKS for the selected robot. '
        'Return only JSON {"tasks":[TaskDefinition,...]} using the supplied schema. No source code. '
        'Use task, never action, in names and descriptions. Do not invent actuators, effectors, commands, units, frames, sensors or capabilities. '
        'Each task must explicitly use robot_id='+json.dumps(robot_id)+'. IDs must be unique; dependencies form an acyclic graph. '
        'Use operation=command with a StandardCommand for direct control or end-effector positioning. '
        'For command tasks emit only id, name, operation, robot_id, dependencies and command (plus known object_id/target_id when needed). '
        'Omit unused task fields. Never set placement, llm_input or llm_system_prompt to null: their schema defaults apply when omitted. '
        'SET_ACTUATOR uses the exact actuator ID, scalar value and its configured unit (rad or m); it bypasses IK. '
        'SET_COMPONENT uses an exact configured component ID and opening percent [0,100]; it bypasses IK. '
        'MOVE_END_EFFECTOR requires an exact effector ID, position [x,y,z] in metres and an explicit configured frame. '
        'Every MOVE_END_EFFECTOR command MUST include position_unit="m" and frame with the exact configured world-frame name. '
        'Optional orientation_rpy=[roll,pitch,yaw] uses radians. Only pose commands invoke IK; never invent joint solutions. '
        'Omit legacy target/joint_positions in command tasks. Set task object_id/target_id when reserving a known object/destination; those are shared-resource associations, not proof of contact. '
        'For the educational analytic arm, grasp/release require a known object_id, a preceding approach and compatible payload. '
        'Immediately before grasp, the tool must reach the exact object center, within 0.012 m. An approach hovering above the object is NOT a grasp pose: add a lowering task to its exact current x,y,z before grasp. '
        'A component opening task alone does not prove grasp or object movement. For other models do not invent contact/grasp support. '
        'Object attachment REQUIRES a separate task with operation="grasp" and object_id. A SET_COMPONENT command named Grasp does not attach or carry anything. '
        'Relative requests must resolve against the supplied current world state; 30 cm means 0.30 m. '
        'For a vertical object lift, final object z = original object z + requested lift in metres; keep original object x,y. '
        'Use that final absolute position in the lift command after grasp, and do not release unless requested. Do not use object size, a previous approach height or an intermediate height instead of original object z. '
        'When GROUNDED_RELATIVE_OBJECT_GOAL is supplied, its required_final_position is mandatory: use those exact coordinates for the final lift and honor must_remain_held. The compiler independently verifies them. '
        'Include approach/grasp/lift when moving an object, rather than only moving an empty tool. '
        'Tasks are reviewed and compiled before execution. Unsupported or ambiguous requests return {"error":"explanation"}. '
        '\nROBOT='+json.dumps(description)+
        '\nCURRENT_JOINTS='+json.dumps(positions)+
        '\nGROUNDED_RELATIVE_OBJECT_GOAL='+json.dumps(relative_object_lift(goal,objects))+
        '\nWORLD_OBJECTS='+json.dumps([o.model_dump() for o in objects])+
        '\nTASK_SCHEMA='+json.dumps(drafting_schema(model,robot_id)))


async def draft_tasks(registry,adapter_id,goal,model,robot_id,objects,positions):
    invoke=registry.adapter(adapter_id)
    system=system_prompt(model,robot_id,objects,positions,goal)
    input=goal
    for attempt in range(2):
        response=await invoke(input,system)
        try:
            data=json_answer(response['answer'])
            if isinstance(data,dict) and 'error' in data:raise ValueError(str(data['error']))
            proposal=TaskProposal.model_validate(data)
            break
        except (json.JSONDecodeError,ValidationError,TypeError) as error:
            if attempt:
                raise ValueError(f'LLM did not return a valid capability-compatible task draft: {error}') from error
            # One model-authored formatting repair, before any save, IK or motion.
            # Unknown targets, units, joint limits and unreachable poses below do not retry.
            input=json.dumps({'original_goal':goal,'invalid_draft':response['answer'][:16000],'schema_error':str(error)[:2000]})
            system += ('\nRepair the malformed draft once. Return only task JSON matching the supplied schema. '
                'Correct JSON formatting and required schema fields only; preserve the original goal, exact targets and units. '
                'Do not substitute an unavailable actuator or change an unreachable requested position. Omit unused optional fields instead of assigning null to non-nullable fields.')
    for task in proposal.tasks:
        if task.robot_id!=robot_id or task.operation=='llm':raise ValueError('Draft changed the assigned robot or introduced an unsolicited LLM task')
        if task.command:resolve_command(model,positions,task.command)
    return proposal.tasks
