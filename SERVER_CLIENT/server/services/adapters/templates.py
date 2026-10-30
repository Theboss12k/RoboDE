"""Documented virtual SDK catalogs, usable without an LLM or hardware SDK."""
from shared.models.robotics import DriverDraft
TEMPLATES={
 'stationary_arm':[('base_yaw','rad',-3.2,3.2),('shoulder','rad',-3.2,3.2),('elbow','rad',-3.2,3.2),('wrist','rad',-6.3,6.3),('gripper','m',0.,.2)],
 'gantry':[('slide_x','m',-10.,10.),('slide_y','m',-10.,10.),('slide_z','m',-10.,10.)],
 'differential_drive':[('left_wheel','rad/s',-50.,50.),('right_wheel','rad/s',-50.,50.)]}
TEMPLATES['mobile_manipulator']=TEMPLATES['stationary_arm']+TEMPLATES['differential_drive']
def template(template_id):
    if template_id not in TEMPLATES:raise ValueError('Unknown virtual SDK template')
    functions=[];quotes=[]
    for joint,unit,minimum,maximum in TEMPLATES[template_id]:
        quote=f'set_{joint}(value) sets {joint} in {unit}; range {minimum} to {maximum}.';quotes.append(quote)
        functions.append({'id':'set_'+joint,'vendor_method':'set_'+joint,'unit':unit,'mode':'velocity' if unit.endswith('/s') else 'position','minimum':minimum,'maximum':maximum,'documentation_quote':quote})
    return DriverDraft(name='RoboDE '+template_id.replace('_',' ')+' virtual SDK',category='virtual',sdk_version='robode-sim-v2',documentation='\n'.join(quotes+['read_feedback() returns simulated actuator feedback.','stop_motion() stops simulated motion.','disconnect() closes the simulated transport.']),functions=functions,feedback_method='read_feedback',stop_method='stop_motion',disconnect_method='disconnect')


def function_id(joint):
    """A catalog-safe function name for a URDF joint ID (which may contain dashes or start with a digit)."""
    import re
    name=re.sub(r'[^a-z0-9_]','_',joint.lower()).strip('_') or 'joint'
    return ('set_'+name)[:80]


def simulator_for(model):
    """A virtual adapter with one function per reviewed actuator, using the model's own limits."""
    import math
    functions=[];quotes=[]
    for joint,spec in model['actuators']['actuators'].items():
        unit,minimum,maximum,mode=spec['unit'],float(spec['min']),float(spec['max']),'position'
        if not (math.isfinite(minimum) and math.isfinite(maximum) and minimum<maximum):
            # Continuous joints (wheels) are commanded by velocity within their rated speed.
            unit,minimum,maximum,mode=spec['unit']+'/s',-float(spec['velocity']),float(spec['velocity']),'velocity'
        fid=function_id(joint)
        quote=f'{fid}(value) sets {joint} in {unit}; range {minimum} to {maximum}.';quotes.append(quote)
        functions.append({'id':fid,'vendor_method':fid,'unit':unit,'mode':mode,'minimum':minimum,'maximum':maximum,'documentation_quote':quote})
    return DriverDraft(name=f"{model['robot']['name']} simulator adapter"[:120],category='virtual',sdk_version='robode-sim-v2',
        documentation='\n'.join(quotes+['read_feedback() returns simulated actuator feedback.','stop_motion() stops simulated motion.','disconnect() closes the simulated transport.']),
        functions=functions,feedback_method='read_feedback',stop_method='stop_motion',disconnect_method='disconnect')
