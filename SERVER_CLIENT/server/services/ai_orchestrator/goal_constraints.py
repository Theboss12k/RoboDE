"""Ground and verify explicit relative vertical object moves, independently of LLM arithmetic."""
import math
import re


def relative_object_lift(goal, objects):
    text=' '.join(goal.lower().split())
    number=r'(?<![-\d.])(\d+(?:\.\d+)?)\s*(cm|centimeters?|centimetres?|m|meters?|metres?)\b'
    distances=list(re.finditer(number+r'\s+(?:directly\s+)?(?:above|upwards?|higher)\b',text))
    if not distances:
        match=re.search(r'\b(?:lift|raise)\b[^.;]{0,80}?'+number,text)
        distances=[match] if match else []
    if len(distances)!=1:return None
    candidates=[]
    for obj in objects:
        if obj.kind!='object':continue
        names={obj.name.lower(),obj.id.lower()}
        if any(re.search(r'\b(?:pick\s+up|lift|raise|move|hold)\s+(?:the\s+)?'+re.escape(name)+r'\b',text) for name in names):
            candidates.append(obj)
    if len(candidates)!=1:return None
    match=distances[0];value=float(match[1]);unit=match[2]
    if not math.isfinite(value):return None
    offset=value/100 if unit.startswith('c') else value
    obj=candidates[0]
    return {'object_id':obj.id,'original_position':obj.position.model_dump(),
        'required_final_position':{'x':obj.position.x,'y':obj.position.y,'z':round(obj.position.z+offset,9)},
        'lift_metres':offset,'must_remain_held':bool(re.search(r'\bhold\b|(?:do not|don\x27t|without)\s+releas',text)),
        'position_tolerance_metres':.003}


def validate_goal_outcome(goal, objects, plan, task_ids=None):
    constraint=relative_object_lift(goal,objects)
    if constraint is None:return
    tick=max((entry['end_tick'] for key,entry in plan.task_schedule.items() if task_ids is None or key in task_ids),default=len(plan.frames)-1)
    frame=plan.frames[min(int(tick),len(plan.frames)-1)]
    actual=frame.objects.get(constraint['object_id'])
    expected=constraint['required_final_position']
    if actual is None or math.dist(tuple(actual.model_dump().values()),tuple(expected.values()))>constraint['position_tolerance_metres']:
        raise ValueError(f"Generated tasks do not satisfy the requested object lift: {constraint['object_id']} must finish at {expected} m. No tasks were saved or executed.")
    if constraint['must_remain_held'] and constraint['object_id'] not in frame.held_objects.values():
        raise ValueError('Generated tasks release the object despite the requested hold. No tasks were saved or executed.')
