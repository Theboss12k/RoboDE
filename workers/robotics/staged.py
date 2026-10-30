"""Deterministic mobile-manipulator fallback, with an explicit stopped transit stage."""
import math
from pathlib import Path
from workers.robotics.native import Engine
from workers.robotics.navigation import navigation_samples
from services.validation.registry import validate_positions


def plan_staged(payload,q,base,goal,objects,folder):
    model=payload['model'];mobility=model['mobility'];engine=Engine(payload,folder/'robot')
    if mobility['priority']=='arm_first':
        try:return engine.plan(q,base,goal,objects)
        except ValueError:pass
    transit=mobility.get('transit_positions')
    if not transit:raise ValueError('BOTH fallback requires a reviewed transit configuration')
    validate_positions(model,transit)
    wheels={mobility['left_wheel'],mobility['right_wheel']};transit={**transit,**{w:q[w] for w in wheels}}
    arm_path=engine.plan(q,base,{'kind':'configuration','positions':transit},objects)['samples']
    bounds=mobility['navigation_bounds'];target=goal['position'];reach=sum(math.sqrt(sum(v*v for v in j.get('origin',{}).get('xyz',[0,0,0]))) for j in model['kinematics']['joints'])
    if reach<=0:raise ValueError('Robot reach is not configured')
    bearing=math.atan2(target[1]-base.get('y',0),target[0]-base.get('x',0));candidates=[]
    for delta in (0,math.pi/2,-math.pi/2,math.pi):
        yaw=bearing+delta;distance=.65*reach;candidate={**base,'x':target[0]-math.cos(yaw)*distance,'y':target[1]-math.sin(yaw)*distance,'yaw':yaw}
        if bounds[0]<=candidate['x']<=bounds[2] and bounds[1]<=candidate['y']<=bounds[3]:candidates.append(candidate)
    errors=[]
    for index,candidate in enumerate(candidates):
        try:
            # Determine stationary arm feasibility before spending time on base navigation.
            finish=engine.plan(transit,candidate,goal,objects)
            navfolder=folder/('navigation_'+str(index));navfolder.mkdir()
            navigation=navigation_samples(model,transit,base,{'kind':'base','position':[candidate['x'],candidate['y']],'yaw':candidate['yaw']},objects,navfolder)
            end=navigation['samples'][-1];finish=engine.plan(end['positions'],end['base_pose'],goal,objects)
            combined=[];clock=0.
            for phase in (arm_path,navigation['samples'],[{'time':0.,**{k:end[k] for k in ('positions','base_pose')}},{'time':.3,**{k:end[k] for k in ('positions','base_pose')}}],finish['samples']):
                for sample in phase[1:] if combined else phase:combined.append({**sample,'time':clock+sample['time']})
                clock+=phase[-1]['time']
            return {'samples':combined,'engine':'MoveIt2 → reviewed transit → Nav2 → stopped base → MoveIt2','stages':['transit','base','stop','arm'],'hardware_validated':False}
        except ValueError as error:errors.append(str(error))
    raise ValueError('No valid staged arm/base configuration found: '+'; '.join(errors or ['No base target lies inside navigation boundaries']))
