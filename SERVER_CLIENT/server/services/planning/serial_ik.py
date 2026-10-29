"""Bounded damped-least-squares IK for configured serial/branched revolute/prismatic trees.

Pure Python, SI units. Point/pose convergence is checked explicitly; this is not a
collision planner. Each joint origin is parent->joint, then joint axis motion.
"""
import math


def mm(a,b):
    return [[sum(x*y for x,y in zip(row,col)) for col in zip(*b)] for row in a]


def transform(xyz=(0.,0.,0.),rpy=(0.,0.,0.)):
    r,p,y=rpy
    cr,sr,cp,sp,cy,sy=math.cos(r),math.sin(r),math.cos(p),math.sin(p),math.cos(y),math.sin(y)
    return [[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr,xyz[0]],
            [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr,xyz[1]],
            [-sp,cp*sr,cp*cr,xyz[2]],[0.,0.,0.,1.]]


def joint_axis(joint):
    vector = joint.get('axis_vector')
    if vector is None:
        vector = [float(joint.get('axis','z') == axis) for axis in 'xyz']
    if len(vector) != 3 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in vector):
        raise ValueError('Joint axes require three finite numbers')
    norm = math.sqrt(sum(v*v for v in vector))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError('Joint axis must have nonzero finite length')
    return [v/norm for v in vector]


def axis_rotation(axis, angle):
    x,y,z = axis; c,s = math.cos(angle),math.sin(angle); d = 1-c
    return [[c+x*x*d,x*y*d-z*s,x*z*d+y*s,0.],
            [y*x*d+z*s,c+y*y*d,y*z*d-x*s,0.],
            [z*x*d-y*s,z*y*d+x*s,c+z*z*d,0.],[0.,0.,0.,1.]]


def validate_chain(model):
    k=model['kinematics']; links={k['world_frame']}; actuators=set(); children=set()
    if not k.get('end_effectors'):
        raise ValueError('serial_chain_dls_v1 requires named end_effectors')
    for j in k['joints']:
        if j['parent'] not in links or j['child'] in links or j['child'] in children:
            raise ValueError('Kinematic joints must form an ordered, acyclic tree with unique child links')
        if j['type']!='fixed':
            if j['actuator'] in actuators or j['actuator'] not in model['actuators']['actuators']:
                raise ValueError('Moving joints need unique configured actuators')
            spec=model['actuators']['actuators'][j['actuator']]
            if spec['type']!=j['type'] or spec['unit']!=('rad' if j['type']=='revolute' else 'm'):
                raise ValueError('Joint type and canonical unit must match its actuator')
            joint_axis(j)
            actuators.add(j['actuator'])
        for vector in j.get('origin',{}).values():
            if len(vector)!=3 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in vector):
                raise ValueError('Joint origins require finite XYZ metres / RPY radians')
        links.add(j['child']);children.add(j['child'])
    for effector in k['end_effectors'].values():
        for key in ('xyz','rpy'):
            vector=effector.get(key,[0.,0.,0.])
            if len(vector)!=3 or not all(isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) for v in vector):raise ValueError('End effector origins require finite XYZ/RPY')
        if effector['link'] not in links:
            raise ValueError('End effector references an undefined link')
    return True


def frames(model,q):
    k=model['kinematics'];base=model.get('base_pose',{})
    out={k['world_frame']:transform([base.get(a,0.) for a in ('x','y','z')],[0.,0.,base.get('yaw',0.)])}
    for j in k['joints']:
        origin=j.get('origin',{}); axis=joint_axis(j) if j['type']!='fixed' else [0.,0.,1.]; value=q.get(j.get('actuator'),0.)
        t=mm(out[j['parent']],transform(origin.get('xyz',[0.,0.,0.]),origin.get('rpy',[0.,0.,0.])))
        if j['type']=='revolute':t=mm(t,axis_rotation(axis,value))
        elif j['type']=='prismatic':t=mm(t,transform(xyz=[a*value for a in axis]))
        out[j['child']]=t
    return out


def effector_frame(model,q,target):
    try: e=model['kinematics']['end_effectors'][target]
    except KeyError as error:raise ValueError(f'Unknown end effector: {target}') from error
    return mm(frames(model,q)[e['link']],transform(e.get('xyz',[0.,0.,0.]),e.get('rpy',[0.,0.,0.])))


def rotation_error(target,current):
    # SO(3) logarithm, including the near-pi case (zero skew is not convergence).
    r=mm([row[:3] for row in target[:3]],list(map(list,zip(*[row[:3] for row in current[:3]]))))
    angle=math.acos(max(-1.,min(1.,(sum(r[i][i] for i in range(3))-1)/2)))
    if angle<1e-8:return [0.,0.,0.]
    if math.pi-angle<1e-5:
        axis=[math.sqrt(max(0.,(r[i][i]+1)/2)) for i in range(3)]
        index=max(range(3),key=lambda i:axis[i])
        for i in range(3):
            if i!=index and axis[index]>1e-8:axis[i]=(r[i][index]+r[index][i])/(4*axis[index])
        return [angle*a for a in axis]
    scale=angle/(2*math.sin(angle))
    return [scale*(r[2][1]-r[1][2]),scale*(r[0][2]-r[2][0]),scale*(r[1][0]-r[0][1])]


def solve_linear(a,b):
    a=[list(row)+[v] for row,v in zip(a,b)];n=len(b)
    for i in range(n):
        pivot=max(range(i,n),key=lambda j:abs(a[j][i]));a[i],a[pivot]=a[pivot],a[i]
        d=a[i][i]
        if abs(d)<1e-12:raise ValueError('Singular IK system')
        a[i]=[v/d for v in a[i]]
        for j in range(n):
            if j!=i:
                d=a[j][i];a[j]=[v-d*w for v,w in zip(a[j],a[i])]
    return [row[-1] for row in a]


def inverse_pose(model,position,orientation,seed,effector):
    validate_chain(model)
    e=model['kinematics']['end_effectors'].get(effector)
    if e is None:raise ValueError(f'Unknown end effector: {effector}')
    # Only ancestors of this effector may move. Other arms and grippers retain state.
    parents={j['child']:j for j in model['kinematics']['joints']};chain=[];link=e['link']
    while link in parents:
        j=parents[link]
        if j['type']!='fixed':chain.append(j['actuator'])
        link=j['parent']
    names=list(reversed(chain));limits=model['actuators']['actuators'];desired=transform(position,orientation or [0.,0.,0.])
    seeds=[dict(seed)]
    seeds += [{**seed,**{k:limits[k]['min']+(limits[k]['max']-limits[k]['min'])*fraction for k in names}} for fraction in (.25,.5,.75)]
    for q in seeds:
        for _ in range(180):
            t=effector_frame(model,q,effector);error=[desired[i][3]-t[i][3] for i in range(3)]
            if orientation is not None:error+=rotation_error(desired,t)
            if math.sqrt(sum(v*v for v in error[:3]))<.0005 and (orientation is None or math.sqrt(sum(v*v for v in error[3:]))<.002):
                return q
            jac=[]
            for key in names:
                shifted=dict(q);shifted[key]+=1e-5;u=effector_frame(model,shifted,effector)
                column=[(u[i][3]-t[i][3])/1e-5 for i in range(3)]
                if orientation is not None:column += [v/1e-5 for v in rotation_error(u,t)]
                jac.append(column)
            # (J.T J + damping I) dq = J.T error.
            normal=[[sum(a*b for a,b in zip(x,y))+(0.0001 if i==j else 0.) for j,y in enumerate(jac)] for i,x in enumerate(jac)]
            delta=solve_linear(normal,[sum(a*b for a,b in zip(column,error)) for column in jac])
            for key,d in zip(names,delta):q[key]=max(limits[key]['min'],min(limits[key]['max'],q[key]+max(-.15,min(.15,d))))
    raise ValueError(f'{effector}: target unreachable or no valid IK solution found within configured limits')
