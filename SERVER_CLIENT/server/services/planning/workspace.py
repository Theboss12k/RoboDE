"""Bounded tool-position sampling using the same FK and limits as the planner."""
import json
from functools import lru_cache
from services.planning.kinematics import supports_model, link_points


@lru_cache(maxsize=32)
def _sample(serialized):
    model = json.loads(serialized)
    limits = model['actuators']['actuators']
    def values(key, count):
        low, high = limits[key]['min'], limits[key]['max']
        # Include zero when valid: it captures straight-link and axial extrema.
        return sorted(set([low+(high-low)*n/(count-1) for n in range(count)] + ([0.] if low<=0<=high else [])))
    positions = {key:(a['min']+a['max'])/2 for key,a in limits.items()}
    points = set()
    for yaw in values('base_yaw',33):
        positions['base_yaw'] = yaw
        for shoulder in values('shoulder',23):
            positions['shoulder'] = shoulder
            for elbow in values('elbow',23):
                positions['elbow'] = elbow
                links = link_points(model,positions)
                # Same centreline table-clearance rule as trajectory validation.
                if all(point[2]>=.022 for point in links[1:]):
                    points.add(tuple(round(value,6) for value in links[-1]))
    points = sorted(points)
    bounds = {'min':[min(p[a] for p in points) for a in range(3)],'max':[max(p[a] for p in points) for a in range(3)]} if points else None
    return {'points':points,'bounds':bounds,'sample_count':len(points)}


def reachable_workspace(model):
    metadata = {'units':'m','frame':'world','method':'joint_limit_fk_samples',
        'scope':'Sampled tool positions with joint limits and table clearance. Obstacles, self-collision, other robots and tool orientation are not checked. Compile a plan to validate a motion.'}
    if not supports_model(model) or model['kinematics']['solver']!='analytic_yaw_two_link_v1':
        return {**metadata,'available':False,'points':[],'bounds':None,'sample_count':0,
            'reason':'Workspace envelope sampling currently supports the analytic demo morphology only. Configured serial-chain FK/IK remains available for pose tasks.' if supports_model(model) else 'Workspace unavailable: this model needs a verified kinematics solver.'}
    # Only geometric inputs affect this cache. Current feedback and simulator state do not.
    relevant = {key:model[key] for key in ('robot','kinematics','actuators')}
    relevant['base_pose'] = model.get('base_pose',{'x':0.,'y':0.,'z':0.,'yaw':0.})
    result = _sample(json.dumps(relevant,sort_keys=True,allow_nan=False))
    return {**metadata,**result,'available':bool(result['points']),
        'reason':None if result['points'] else 'No sampled tool positions satisfy joint limits and table clearance.'}
