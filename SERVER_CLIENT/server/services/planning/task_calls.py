"""Deterministic compatibility projection; never rewrites saved legacy tasks."""
from shared.models.robotics import FunctionCall
from services.ai_orchestrator.two_stage import catalog

def legacy_calls(task,model,instance):
    available=catalog(model)
    def actuator(joint,value):
        f=next((f for f in available if f['kind']=='actuator' and f['target']==joint and f['control_mode']=='position'),None)
        if not f:raise ValueError(task.id+': legacy joint needs an approved position-control function')
        return FunctionCall(function=f['id'],arguments={'value':value,'unit':f['arguments']['unit']})
    if task.operation=='command' and task.command:
        c=task.command
        if c.type=='SET_ACTUATOR':return [actuator(c.target,c.value)]
        if c.type=='SET_COMPONENT':return [FunctionCall(function='component_'+c.target,arguments={'value':c.value,'unit':'percent'})]
        return [FunctionCall(function='MOVE',arguments={'target':c.target,'position':c.position,'frame':c.frame,**({'orientation_rpy':c.orientation_rpy} if c.orientation_rpy is not None else {})})]
    if task.operation=='move':
        if task.target:
            move=next(f for f in available if f['id']=='MOVE')
            return [FunctionCall(function='MOVE',arguments={'target':move['targets'][0],'position':[task.target.x,task.target.y,task.target.z],'frame':model['kinematics']['world_frame']})]
        return [actuator(k,v) for k,v in (task.joint_positions or instance['initial_configuration']['actuator_positions']).items()]
    if task.operation in {'grasp','release'} or task.operation=='verify' and task.object_id:
        return [FunctionCall(function=task.operation.upper(),arguments={'object_id':task.object_id,**({'target_id':task.target_id,'placement':task.placement} if task.target_id else {})})]
    return []
