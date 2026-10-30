"""Compile catalog calls into one synchronized, immutable motion revision."""
import copy
import math
import uuid
from shared.models.domain import Plan,Frame,TaskSpec,TaskStep,TaskDefinition,Check,Pose
from services.ai_orchestrator.two_stage import normalize_call,task_signature
from services.planning.definitions import validate_definition
from services.task_engine.graph import topological_order
from services.planning.motion_client import MotionClient,MotionUnavailable
from services.planning.physical_checker import check_plan
from services.commands.standard import resolve_command
from shared.models.command import StandardCommand
from services.world_model.world import object_map,placement_satisfied
from services.planning.kinematics import forward


def preview_goal(model,q,base,goal):
    """Portable preview only; full collision coverage comes from the Linux worker."""
    target=dict(q);end=dict(base)
    if goal['kind']=='joint':target[goal['joint']]=goal['value']
    elif goal['kind']=='tool':
        target=resolve_command({**model,'base_pose':base},q,StandardCommand(type='MOVE_END_EFFECTOR',target=goal['target'],position=goal['position'],position_unit='m',frame=goal['frame'],orientation_rpy=goal.get('orientation_rpy'),orientation_unit='rad' if goal.get('orientation_rpy') is not None else None))
    elif goal['kind']=='base':end.update(x=goal['position'][0],y=goal['position'][1],yaw=goal.get('yaw',base.get('yaw',0)))
    else:raise ValueError('Unsupported preview motion')
    duration=.5
    for key,v in q.items():
        a=model['actuators']['actuators'][key];delta=abs(target[key]-v)
        duration=max(duration,1.95*delta/a['velocity'],math.sqrt(6.2*delta/a['acceleration']))
    mobility=model.get('mobility',{})
    duration=max(duration,1.95*math.hypot(end.get('x',0)-base.get('x',0),end.get('y',0)-base.get('y',0))/mobility.get('max_linear_m_s',.2),1.95*abs(end.get('yaw',0)-base.get('yaw',0))/mobility.get('max_angular_rad_s',.5))
    count=max(15,math.ceil(duration*30));result=[]
    for n in range(count+1):
        t=n/count;s=10*t**3-15*t**4+6*t**5
        result.append({'time':n/30,'positions':{k:q[k]+(target[k]-q[k])*s for k in q},'base_pose':{k:base.get(k,0)+(end.get(k,0)-base.get(k,0))*s for k in ('x','y','z','yaw')}})
    return result


def sample_path(path,t):
    """Interpolate the approved path; never select an early/late nearest sample."""
    import bisect
    index=bisect.bisect_right([s['time'] for s in path],t)
    if index==0:return path[0]
    if index>=len(path):return path[-1]
    a,b=path[index-1:index+1];duration=b['time']-a['time'];u=(t-a['time'])/duration
    q={k:a['positions'][k]+u*(v-a['positions'][k]) for k,v in b['positions'].items()}
    if a.get('velocities') and b.get('velocities'):
        q={k:(2*u**3-3*u**2+1)*a['positions'][k]+(u**3-2*u**2+u)*duration*a['velocities'][k]+(-2*u**3+3*u**2)*v+(u**3-u**2)*duration*b['velocities'][k] for k,v in b['positions'].items()}
    return {**a,'time':t,'positions':q,'base_pose':{k:a['base_pose'].get(k,0)+u*(b['base_pose'].get(k,0)-a['base_pose'].get(k,0)) for k in ('x','y','z','yaw')}}


async def compile_v2(store,definition,cell,states,stamp,client=None):
    validate_definition(definition,set(cell.instances))
    if definition.planning_status in {'needs_clarification','unsupported'}:raise ValueError('Resolve planning questions before validation')
    if not definition.tasks:raise ValueError('Add tasks first')
    if any(m.get('binding_stale') for m in cell.models.values()):raise ValueError('Robot mapping changed. Select and test a current published binding in Robots before compiling')
    client=client or MotionClient(store)
    current={rid:dict(s.positions) for rid,s in states.items()};bases={rid:dict(s.base_pose or cell.instances[rid].get('base_pose',{'x':0,'y':0,'z':0,'yaw':0})) for rid,s in states.items()}
    objects=[o.model_copy(deep=True) for o in cell.objects];held=dict.fromkeys(cell.instances);held_tools=dict.fromkeys(cell.instances)
    tasks=[t.model_copy(deep=True) for t in definition.tasks]
    primary=next(iter(cell.instances));answers={}
    from services.planning.task_calls import legacy_calls
    for task in tasks:
        if task.binding_status=='legacy' and task.operation!='llm':task.function_calls=legacy_calls(task,cell.models[task.robot_id],cell.instances[task.robot_id])
    previous={}
    preliminary=[TaskStep(id=t.id,label=t.name,operation='command',robot_id=t.robot_id,dependencies=t.dependencies,implementation='catalog') for t in tasks]
    task_by_id={t.id:t for t in tasks}
    for t in (task_by_id[s.id] for s in topological_order(preliminary)):
        if t.binding_status=='unresolved':raise ValueError(t.id+': resolve task calls before validation')
        if t.binding_status=='resolved' and t.operation!='llm' and t.binding_fingerprint!=task_signature(t,cell.models[t.robot_id]):raise ValueError(t.id+': command binding is stale')
        for resource in ([*cell.instances] if t.operation=='llm' else [t.robot_id])+[v for v in (t.object_id,t.target_id) if v]:
            if resource in previous and previous[resource] not in t.dependencies:t.dependencies.append(previous[resource])
            previous[resource]=t.id
    steps=[TaskStep(id=t.id,label=t.name,robot_id=t.robot_id or None,operation='llm' if t.operation=='llm' else 'command',dependencies=t.dependencies,implementation='validated_catalog_dispatch') for t in tasks]
    order=topological_order(steps);by_id={t.id:t for t in tasks};local={};schedule={};motion_manifest=[]
    for step in order:
        t=by_id[step.id];rid=t.robot_id or primary;model=cell.models[rid];qs=current[rid];base=bases[rid]
        if t.operation=='llm':
            import re
            from services.ai_orchestrator.llm import LLMRegistry
            text=re.sub(r'\{\{tasks\.([a-zA-Z0-9_:-]+)\.answer\}\}',lambda m:answers[m[1]]['answer'],t.llm_input)
            answers[t.id]=await LLMRegistry(store).adapter(t.llm_adapter_id)(text,t.llm_system_prompt)
        if not t.function_calls and t.operation not in {'llm','verify'}:raise ValueError(t.id+': task has no resolved function calls')
        commands=[normalize_call(c,model) for c in t.function_calls];samples=[];clock=0.
        if not commands:samples=[{'time':time,'positions':dict(qs),'base_pose':dict(base),'objects':object_map(objects),'held':held[rid],'held_tool':held_tools[rid]} for time in (0.,.1)];clock=.1
        for repeat in range(t.repeat_count):
            for goal in commands:
                previous_held=held[rid];previous_tool=held_tools[rid];contact_time=None
                if goal['kind'] in {'grasp','release','verify'}:
                    oid=goal.get('object_id');item=next((o for o in objects if o.id==oid),None)
                    if not item:raise ValueError('Unknown task object')
                    if goal['kind']=='grasp':
                        if held[rid] or oid in held.values() or item.mass_kg>model['capabilities']['payload_kg']:raise ValueError('Object is held or exceeds payload')
                        p=forward({**model,'base_pose':base},qs,goal.get('end_effector'))
                        if math.dist([p.x,p.y,p.z],[item.position.x,item.position.y,item.position.z])>.012:raise ValueError('Grasp task requires contact at the object centre')
                        held[rid]=oid;held_tools[rid]=goal['end_effector']
                    elif goal['kind']=='release':
                        if held[rid]!=oid:raise ValueError('Robot is not holding this object')
                        held[rid]=None;held_tools[rid]=None
                    else:
                        target=next((o for o in objects if o.id==goal.get('target_id')),None)
                        if not target or oid in held.values() or not placement_satisfied(item,target,goal.get('placement','inside')):raise ValueError('Placement verification failed')
                    if goal['kind'] in {'grasp','release'}:
                        from services.commands.standard import tool_component
                        spec=tool_component(model,goal['end_effector'])
                        if not spec:raise ValueError('Grasp/release requires a reviewed gripper component')
                        target=spec['open'] if goal['kind']=='release' else (min(max(item.size.x,model['actuators']['actuators'][spec['actuator']]['min']),model['actuators']['actuators'][spec['actuator']]['max']) if model['actuators']['actuators'][spec['actuator']]['unit']=='m' else spec['closed'])
                        path=preview_goal(model,qs,base,{'kind':'joint','joint':spec['actuator'],'value':target})
                        if goal['kind']=='grasp':
                            contact_time=path[-1]['time'];closed_q=path[-1]['positions'];point=forward({**model,'base_pose':base},closed_q,goal['end_effector'])
                            verify_goal={'kind':'tool','target':goal['end_effector'],'position':[point.x,point.y,point.z+.015],'frame':model['kinematics']['world_frame']}
                            try:verify=(await client.plan(model,closed_q,base,verify_goal,[o for o in objects if o.id!=oid]))['samples']
                            except MotionUnavailable:verify=preview_goal(model,closed_q,base,verify_goal)
                            path=path+[{**s,'time':contact_time+s['time']} for s in verify[1:]]
                    else:path=[{'time':0.,'positions':dict(qs),'base_pose':dict(base)},{'time':.1,'positions':dict(qs),'base_pose':dict(base)}]
                elif goal['kind']=='joint_velocity':
                    if not t.duration_seconds:raise ValueError('Velocity control requires a finite duration')
                    duration=math.ceil(t.duration_seconds*30)/30;acceleration=model['actuators']['actuators'][goal['joint']]['acceleration']
                    if math.pi*abs(goal['value'])/duration>acceleration:raise ValueError('Velocity task duration is too short for bounded acceleration and stopping')
                    path=[{'time':n/30,'positions':{**qs,goal['joint']:qs[goal['joint']]+goal['value']*(n/60-duration*math.sin(2*math.pi*n/(30*duration))/(4*math.pi))},'base_pose':dict(base)} for n in range(round(duration*30)+1)]
                else:
                    try:planned=await client.plan(model,qs,base,goal,objects);path=planned['samples']
                    except MotionUnavailable:
                        # No full-coverage qualification is inferred from this preview.
                        path=preview_goal(model,qs,base,goal)
                coupling=model.get('binding',{}).get('definition',{}).get('joints',[])
                for sample in path:
                    for _ in coupling:
                        for joint in coupling:
                            if joint['role']=='coupled':
                                sample['positions'][joint['joint_id']]=sample['positions'][joint['coupled_to']]*joint['multiplier']+joint['offset']
                                if sample.get('velocities'):sample['velocities'][joint['joint_id']]=sample['velocities'][joint['coupled_to']]*joint['multiplier']
                if len(path)<2 or path[0]['time']!=0 or any(b['time']<=a['time'] for a,b in zip(path,path[1:])):raise ValueError('Motion worker returned invalid trajectory timing')
                if any(set(s['positions'])!=set(qs) for s in path):raise ValueError('Motion worker omitted joint setpoints')
                if any(abs(path[0]['positions'][k]-v)>1e-6 for k,v in qs.items()):raise ValueError('Motion worker trajectory does not start at the approved state')
                for s in path[1:] if samples else path:
                    sample_held=held[rid] if goal['kind'] not in {'grasp','release'} or s['time']>=(contact_time if contact_time is not None else path[-1]['time'])-1e-9 else previous_held
                    sample_tool=held_tools[rid] if sample_held==held[rid] else previous_tool
                    if sample_held:
                        p=forward({**model,'base_pose':s['base_pose']},s['positions'],sample_tool);next(o for o in objects if o.id==sample_held).position=p
                    samples.append({'time':clock+s['time'],'positions':dict(s['positions']),'velocities':s.get('velocities'),'base_pose':dict(s['base_pose']),'objects':object_map(objects),'held':sample_held,'held_tool':sample_tool})
                clock+=path[-1]['time'];clock=math.ceil((clock-1e-9)*30)/30
                if clock>samples[-1]['time']+1e-9:samples.append({**samples[-1],'time':clock,'velocities':{k:0. for k in qs}})
                qs=path[-1]['positions'];base=path[-1]['base_pose']
        if not samples:raise ValueError('No motion samples produced')
        start=max((schedule[d]['end']+1/30 for d in t.dependencies),default=0)
        start=round(start*30)/30
        local[t.id]=samples;schedule[t.id]={'start':start,'end':round((start+clock)*30)/30};current[rid]=dict(qs);bases[rid]=dict(base)
        motion_manifest.append({'id':t.id,'robot_id':rid,'calls':[c.model_dump() for c in t.function_calls],'dependencies':t.dependencies,'normalized':commands})
    duration=round(max(s['end'] for s in schedule.values())*30)/30;frames=[];primary=next(iter(cell.instances))
    for tick in range(max(2,round(duration*30))+1):
        time=min(tick/30,duration);q={rid:dict(s.positions) for rid,s in states.items()};b={rid:dict(s.base_pose or cell.instances[rid].get('base_pose',{})) for rid,s in states.items()};world=object_map(cell.objects);holding=dict.fromkeys(cell.instances);tools_holding=dict.fromkeys(cell.instances);active={}
        for step in order:
            if time+1e-9<schedule[step.id]['start']:continue
            samples=local[step.id];rel=time-schedule[step.id]['start'];sample=sample_path(samples,rel)
            rid=step.robot_id or primary;q[rid]=sample['positions'];b[rid]=sample['base_pose'];holding[rid]=sample['held'];tools_holding[rid]=sample.get('held_tool')
            for oid in sample['objects']:
                if oid in {g.get('object_id') for g in next(m for m in motion_manifest if m['id']==step.id)['normalized']} or sample['held']==oid:world[oid]=sample['objects'][oid]
            if time<=schedule[step.id]['end']+1e-9:active[rid]=step.id
        pending_grasps={rid:{'object_id':g['object_id'],'end_effector':g['end_effector']} for rid,tid in active.items() for g in next(m for m in motion_manifest if m['id']==tid)['normalized'] if g['kind']=='grasp'}
        frames.append(Frame(time=time,step_id=next(iter(active.values()),order[-1].id),positions=q[primary],robot_positions=q,objects=world,held_objects=holding,held_object=holding[primary],active_steps=active,base_poses=b,held_tools=tools_holding,pending_grasps=pending_grasps))
    for entry in schedule.values():
        entry['start_tick']=next(i for i,f in enumerate(frames) if f.time>=entry['start']-1e-9)
        entry['end_tick']=next((i for i,f in enumerate(frames) if f.time>=entry['end']-1e-9),len(frames)-1)
    # Include a final active sample so zero-duration verification/feedback tasks execute.
    for step in order:
        if not any(step.id in f.active_steps.values() for f in frames):raise ValueError('Task has no executable duration')
    report=await check_plan(client,cell.models,frames,cell.objects)
    checks=[Check(id='physical_checker',label='Physical checker',status='failed' if report.status=='failed' else 'warning' if report.status=='incomplete' else 'passed',message='; '.join(f.message for f in report.findings) or 'Complete trajectory geometry and motion checks passed')]
    spec=TaskSpec(id=definition.id,description=definition.goal or definition.name,robot_id=primary,template='multi_robot',required_capabilities=[],success_condition='Every resolved task completes and feedback is verified',steps=steps,provider='Two-stage planner')
    return Plan(id=uuid.uuid4().hex[:12],project_id=definition.project_id,definition_id=definition.id,definition_version=definition.version,task=spec,
        checks=checks,frames=frames,code=__import__('json').dumps(motion_manifest,indent=2),duration=duration,
        valid=report.status!='failed',fingerprint=stamp,adapter=cell.backend,atomic_tasks=tasks,task_schedule=schedule,validation_report=report,
        motion_manifest={'schema_version':2,'tasks':motion_manifest,'llm_answers':answers,'ideal_grasps':cell.backend=='mock'})
