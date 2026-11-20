"""Analytic solver for the demo arm only. Units: metres/radians, Z up."""
import math
import copy
from shared.models.domain import Pose
from services.validation.registry import validate_positions


def supports_model(model):
    if model['kinematics']['solver']=='serial_chain_dls_v1':
        from services.planning.serial_ik import validate_chain
        try:return validate_chain(model)
        except (ValueError,KeyError,TypeError):return False
    expected = {'base_yaw':('z','revolute'),'shoulder':('y','revolute'),'elbow':('y','revolute'),'wrist':('y','revolute'),'gripper':('x','prismatic')}
    joints = model['kinematics']['joints']
    return (model['kinematics']['solver']=='analytic_yaw_two_link_v1'
        and set(model['actuators']['actuators'])==set(expected)
        and set(model['kinematics']['links'])=={'base_height','upper_arm','forearm'}
        and [(j['actuator'],j['parent'],j['child']) for j in joints]==[('base_yaw','world','base'),('shoulder','base','upper_arm'),('elbow','upper_arm','forearm'),('wrist','forearm','tool'),('gripper','tool','fingers')]
        and len(joints)==5
        and all((j['axis'],j['type'])==expected.get(j['actuator']) for j in joints)
        and all(a['unit']==('m' if key=='gripper' else 'rad') for key,a in model['actuators']['actuators'].items()))


def require_solver(model):
    if not supports_model(model):
        raise ValueError(f"{model['robot']['name']}: model configuration is available, but its kinematics has no verified planner. Import a supported analytic model or integrate a tested solver before compiling motion.")


def with_base(model, instance):
    result = copy.deepcopy(model)
    result["base_pose"] = instance.get("base_pose", {"x": 0., "y": 0., "z": 0., "yaw": 0.})
    return result


def link_points(model: dict, q: dict[str, float]) -> list[tuple[float, float, float]]:
    require_solver(model)
    if model['kinematics']['solver']=='serial_chain_dls_v1':
        from services.planning.serial_ik import frames
        return [tuple(t[i][3] for i in range(3)) for t in frames(model,q).values()]
    links = model["kinematics"]["links"]
    h, a, b = links["base_height"], links["upper_arm"], links["forearm"]
    yaw, shoulder, elbow = q["base_yaw"], q["shoulder"], q["elbow"]
    r1, z1 = a * math.cos(shoulder), h + a * math.sin(shoulder)
    r2, z2 = r1 + b * math.cos(shoulder + elbow), z1 + b * math.sin(shoulder + elbow)
    points = [(0, 0, 0), (0, 0, h), (r1 * math.cos(yaw), r1 * math.sin(yaw), z1),
              (r2 * math.cos(yaw), r2 * math.sin(yaw), z2)]
    base = model.get("base_pose", {"x": 0., "y": 0., "z": 0., "yaw": 0.})
    c, s = math.cos(base["yaw"]), math.sin(base["yaw"])
    return [(base["x"] + c*x-s*y, base["y"] + s*x+c*y, base["z"]+z) for x,y,z in points]


def forward(model: dict, q: dict[str, float], target: str | None = None) -> Pose:
    if model['kinematics']['solver']=='serial_chain_dls_v1':
        from services.planning.serial_ik import effector_frame
        names=list(model['kinematics']['end_effectors'])
        if target is None and len(names)!=1:raise ValueError('Select a named end effector for a multi-effector robot')
        t=effector_frame(model,q,target or names[0]);return Pose(x=t[0][3],y=t[1][3],z=t[2][3])
    x, y, z = link_points(model, q)[-1]
    return Pose(x=x, y=y, z=z)


def tool_reach(model: dict) -> dict:
    """How far each tool can get from a fixed point, in the world frame, for the LLM planner and converter.

    The analytic arm's tool reaches between |upper_arm - forearm| and upper_arm + forearm from its shoulder. A serial
    chain's bound is the sum of the joint offsets and prismatic travel after its first moving joint. Joint limits and
    table clearance can exclude parts of that shell; inverse kinematics during motion planning stays authoritative."""
    if not supports_model(model) or model.get('mobility',{}).get('classification','STATIONARY')!='STATIONARY':return {}
    k=model['kinematics'];base=model.get('base_pose',{})
    def point(xyz):return [round(v,4) for v in xyz]
    if k['solver']=='analytic_yaw_two_link_v1':
        from services.commands.standard import effectors
        a,b=k['links']['upper_arm'],k['links']['forearm']
        centre=point([base.get('x',0.),base.get('y',0.),base.get('z',0.)+k['links']['base_height']])
        return {tool:{'centre':centre,'max_m':round(a+b,4),'min_m':round(abs(a-b),4)} for tool in effectors(model)}
    from services.planning.serial_ik import frames
    by_child={j['child']:j for j in k['joints']};zero=frames(model,{})
    result={}
    for tool,e in k.get('end_effectors',{}).items():
        chain,link=[],e['link']
        while link in by_child:chain.insert(0,by_child[link]);link=by_child[link]['parent']
        moving=[i for i,j in enumerate(chain) if j['type']!='fixed']
        if not moving:continue
        first=chain[moving[0]];limits=model['actuators']['actuators']
        length=sum(math.hypot(*j.get('origin',{}).get('xyz',[0.,0.,0.])) for j in chain[moving[0]+1:])+math.hypot(*e.get('xyz',[0.,0.,0.]))
        length+=sum(max(abs(limits[j['actuator']]['min']),abs(limits[j['actuator']]['max'])) for j in chain[moving[0]:] if j['type']=='prismatic')
        result[tool]={'centre':point([zero[first['child']][i][3] for i in range(3)]),'max_m':round(length,4),'min_m':0.}
    return result


def inverse(model: dict, target: Pose, gripper: float = 0.08) -> dict[str, float]:
    require_solver(model)
    if model['kinematics']['solver']=='serial_chain_dls_v1':
        from services.planning.serial_ik import inverse_pose
        names=list(model['kinematics']['end_effectors'])
        if len(names)!=1:raise ValueError('Use a standardized command with a named end effector')
        seed={k:(v['min']+v['max'])/2 for k,v in model['actuators']['actuators'].items()}
        return inverse_pose(model,[target.x,target.y,target.z],None,seed,names[0])
    base = model.get("base_pose", {"x": 0., "y": 0., "z": 0., "yaw": 0.})
    dx, dy = target.x-base["x"], target.y-base["y"]
    c, s = math.cos(base["yaw"]), math.sin(base["yaw"])
    target = Pose(x=c*dx+s*dy, y=-s*dx+c*dy, z=target.z-base["z"])
    if model["kinematics"]["solver"] != "analytic_yaw_two_link_v1":
        raise ValueError("No verified kinematics solver for this model")
    links = model["kinematics"]["links"]
    a, b = links["upper_arm"], links["forearm"]
    radius, height = math.hypot(target.x, target.y), target.z - links["base_height"]
    cosine = (radius**2 + height**2 - a**2 - b**2) / (2 * a * b)
    if abs(cosine) > 1 + 1e-9:
        raise ValueError(f"Target ({target.x:.3f}, {target.y:.3f}, {target.z:.3f}) m is outside the demo arm workspace")
    elbow = -math.acos(max(-1, min(1, cosine)))
    shoulder = math.atan2(height, radius) - math.atan2(b * math.sin(elbow), a + b * math.cos(elbow))
    q = {"base_yaw": math.atan2(target.y, target.x), "shoulder": shoulder, "elbow": elbow,
         "wrist": -shoulder - elbow, "gripper": gripper}
    validate_positions(model, q)
    return q


def link_segments(model,q):
    if model['kinematics']['solver']=='serial_chain_dls_v1':
        from services.planning.serial_ik import frames
        f=frames(model,q)
        return [(tuple(f[j['parent']][i][3] for i in range(3)),tuple(f[j['child']][i][3] for i in range(3))) for j in model['kinematics']['joints']]
    points=link_points(model,q)
    return list(zip(points,points[1:]))
