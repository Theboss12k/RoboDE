"""Conservative interval certification for synchronized collision geometry.

A disjoint bound proves separation. Overlapping bounds are subdivided and checked
with MoveIt; an unresolved bound is Incomplete. No sampling-only certificate.
"""
import math
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from shared.models.robotics import ValidationFinding


def shapes(engine):
    result=[];missing=[]
    for link in engine.root.findall('link'):
        if link.findall('visual') and not link.findall('collision'):missing.append(link.get('name'))
        for collision in link.findall('collision'):
            origin=collision.find('origin');matrix=np.eye(4)
            if origin is not None:
                matrix[:3,3]=list(map(float,origin.get('xyz','0 0 0').split()));matrix[:3,:3]=Rotation.from_euler('xyz',list(map(float,origin.get('rpy','0 0 0').split()))).as_matrix()
            geometry=next(iter(collision.find('geometry')))
            if geometry.tag=='box':extent=np.array(list(map(float,geometry.get('size').split())))/2
            elif geometry.tag=='sphere':extent=np.array([float(geometry.get('radius'))]*3)
            elif geometry.tag=='cylinder':extent=np.array([float(geometry.get('radius')),float(geometry.get('radius')),float(geometry.get('length'))/2])
            elif geometry.tag=='mesh':
                import trimesh
                from urllib.parse import urlparse,unquote
                mesh=trimesh.load(unquote(urlparse(geometry.get('filename')).path),force='mesh',process=False)
                scale=np.array(list(map(float,geometry.get('scale','1 1 1').split())))
                vertices=np.asarray(mesh.vertices)*scale
                if vertices.size==0 or len(vertices)>1_000_000:raise ValueError('Mesh collision bounds unavailable or too complex')
                minimum,maximum=vertices.min(axis=0),vertices.max(axis=0);extent=(maximum-minimum)/2;translation=np.eye(4);translation[:3,3]=(minimum+maximum)/2;matrix=matrix@translation
            else:raise ValueError('Unsupported collision geometry: '+geometry.tag)
            if not np.isfinite(extent).all() or np.any(extent<=0):raise ValueError('Invalid collision dimensions')
            corners=np.array([[sx*extent[0],sy*extent[1],sz*extent[2],1.] for sx in (-1,1) for sy in (-1,1) for sz in (-1,1)])
            result.append({'link':link.get('name'),'origin':matrix,'corners':corners,'radius':float(np.linalg.norm(extent)+np.linalg.norm(matrix[:3,3]))})
    if not result:raise ValueError('URDF has no collision shapes')
    return result,missing


def bounds(engine,geometry,q,base):
    state=engine.state_for(q,base);result=[]
    for shape in geometry:
        transform=np.asarray(state.get_global_link_transform(shape['link']))@shape['origin'];points=(transform@shape['corners'].T).T[:,:3]
        result.append((shape['link'],points.min(axis=0),points.max(axis=0)))
    return result


def pad(engine,geometry,q0,q1,b0,b1):
    # Path-independent upper bound on every collision point's travel for linear
    # joint interpolation. Triangle inequality includes every kinematic branch.
    reach=sum(math.sqrt(sum(float(v)**2 for v in j.find('origin').get('xyz','0 0 0').split())) if j.find('origin') is not None else 0. for j in engine.root.findall('joint'))+max(g['radius'] for g in geometry)+max((math.sqrt(sum(v*v for v in e.get('xyz',[0,0,0]))) for e in engine.model['kinematics'].get('end_effectors',{}).values()),default=0.)
    distance=math.dist([b0.get(k,0) for k in ('x','y','z')],[b1.get(k,0) for k in ('x','y','z')])+abs(b1.get('yaw',0)-b0.get('yaw',0))*reach
    for key,a in engine.model['actuators']['actuators'].items():distance+=abs(q1[key]-q0[key])*(reach if a['unit']=='rad' else 1.)
    return distance+1e-8


def overlap(a,b):return bool(np.all(a[1]<=b[2]) and np.all(b[1]<=a[2]))

def interval_risk(engines,geometry,frames,objects):
    first,last=frames;boxes={};risks=[]
    for rid,engine in engines.items():
        q0,q1=first['robot_positions'][rid],last['robot_positions'][rid];b0=first.get('base_poses',{}).get(rid,engine.model.get('base_pose',{}));b1=last.get('base_poses',{}).get(rid,b0)
        margin=pad(engine,geometry[rid],q0,q1,b0,b1);boxes[rid]=[(link,low-margin,high+margin) for link,low,high in bounds(engine,geometry[rid],q0,b0)]
        binding=engine.model.get('binding',{}).get('definition',{});workspace=binding.get('workspace_bounds');navigation=binding.get('mobility',{}).get('navigation_bounds')
        if workspace:
            for tool in engine.model['kinematics'].get('end_effectors',{}).values():
                transform=np.asarray(engine.state.get_global_link_transform(tool['link']));point=(transform@np.array([*tool.get('xyz',[0,0,0]),1.]))[:3]
                if np.any(point-margin<np.array(workspace[:3])) or np.any(point+margin>np.array(workspace[3:])):risks.append((rid,'workspace',tool['link'],''))
        if navigation:
            footprint=binding['mobility'].get('footprint',[])
            for x,y in footprint:
                px=b0.get('x',0)+x*math.cos(b0.get('yaw',0))-y*math.sin(b0.get('yaw',0));py=b0.get('y',0)+x*math.sin(b0.get('yaw',0))+y*math.cos(b0.get('yaw',0))
                if px-margin<navigation[0] or py-margin<navigation[1] or px+margin>navigation[2] or py+margin>navigation[3]:risks.append((rid,'navigation boundary','footprint',''));break
        adjacent={frozenset((j.find('parent').get('link'),j.find('child').get('link'))) for j in engine.root.findall('joint')}
        for i,a in enumerate(boxes[rid]):
            for b in boxes[rid][i+1:]:
                if a[0]!=b[0] and frozenset((a[0],b[0])) not in adjacent and overlap(a,b):risks.append((rid,'self',a[0],b[0]))
    ids=list(boxes)
    for i,rid in enumerate(ids):
        for other in ids[i+1:]:
            if any(overlap(a,b) for a in boxes[rid] for b in boxes[other]):risks.append((rid,'concurrent',other,''))
    object_boxes=[];owners={}
    for frame in (first,last):
        for rid,oid in frame.get('held_objects',{}).items():
            if oid:owners[oid]=(rid,frame.get('held_tools',{}).get(rid))
        for rid,pending in frame.get('pending_grasps',{}).items():owners[pending['object_id']]=(rid,pending['end_effector'])
    for obj in objects:
        if obj['kind']=='region':continue
        p0=first.get('objects',{}).get(obj['id'],obj['position']);p1=last.get('objects',{}).get(obj['id'],obj['position']);size=np.array([obj['size'][k]/2 for k in ('x','y','z')]);a=np.array([p0[k] for k in ('x','y','z')]);b=np.array([p1[k] for k in ('x','y','z')]);margin=0.
        if obj['id'] in owners:
            rid,_=owners[obj['id']];engine=engines[rid];b0=first.get('base_poses',{}).get(rid,{});b1=last.get('base_poses',{}).get(rid,b0)
            size=np.full(3,float(np.linalg.norm(size)))  # Covers payload rotation without inventing an observed orientation.
            margin=pad(engine,geometry[rid],first['robot_positions'][rid],last['robot_positions'][rid],b0,b1)
        object_boxes.append((obj['id'],np.minimum(a,b)-size-margin,np.maximum(a,b)+size+margin))
    for rid,robot_boxes in boxes.items():
        for item in object_boxes:
            owner=owners.get(item[0]);touch=[]
            if owner and owner[0]==rid:touch=engines[rid].model.get('binding',{}).get('definition',{}).get('grasp_contacts',{}).get(owner[1],[])
            if any(overlap(a,item) for a in robot_boxes if a[0] not in touch):risks.append((rid,'environment/payload',item[0],''))
    for item in object_boxes:
        if item[0] not in owners:continue
        if any(item[0]!=other[0] and overlap(item,other) for other in object_boxes):risks.append((owners[item[0]][0],'carried object/environment',item[0],''))
    return risks


def interpolate(a,b):
    result={'time':(a['time']+b['time'])/2,'active_steps':a.get('active_steps',{}),'held_objects':a.get('held_objects',{}),'held_tools':a.get('held_tools',{}),'pending_grasps':a.get('pending_grasps',{})}
    result['robot_positions']={rid:{k:(v+b['robot_positions'][rid][k])/2 for k,v in q.items()} for rid,q in a['robot_positions'].items()}
    result['base_poses']={rid:{k:(v+b.get('base_poses',{}).get(rid,pose).get(k,v))/2 for k,v in pose.items()} for rid,pose in a.get('base_poses',{}).items()}
    result['objects']={oid:{k:(v+b.get('objects',{}).get(oid,p).get(k,v))/2 for k,v in p.items()} for oid,p in a.get('objects',{}).items()}
    return result


def certify(engines,frames,objects):
    geometry={};findings=[]
    for rid,engine in engines.items():
        try:
            geometry[rid],missing=shapes(engine)
            if missing:findings.append(ValidationFinding(code='MISSING_COLLISION',message='Visual links lack reviewed collision geometry: '+', '.join(missing),robot_id=rid))
        except Exception as error:findings.append(ValidationFinding(code='MISSING_COLLISION',message=str(error),robot_id=rid))
    if len(geometry)!=len(engines):return findings,False
    for frame in frames:
        for rid,oid in frame.get('held_objects',{}).items():
            if not oid:continue
            tool=frame.get('held_tools',{}).get(rid);policy=engines[rid].model.get('binding',{}).get('definition',{}).get('grasp_contacts',{})
            if not tool or not policy.get(tool):
                findings.append(ValidationFinding(code='GRASP_CONTACT_POLICY',message='Carried objects require reviewed tool selection and touch links',robot_id=rid));return findings,False
    budget=[0]
    def check(a,b,depth=0):
        risks=interval_risk(engines,geometry,(a,b),objects)
        if not risks:return True
        mid=interpolate(a,b)
        for rid,engine in engines.items():
            if engine.collision(mid['robot_positions'][rid],mid.get('base_poses',{}).get(rid)):
                findings.append(ValidationFinding(code='COLLISION',message='MoveIt detects collision between trajectory samples (marker shows the tool pose)',position=engine.failure_position,robot_id=rid,task_id=mid['active_steps'].get(rid),time=mid['time']));return False
        if depth>=7 or budget[0]>6000:
            rid,kind,link,other=risks[0];findings.append(ValidationFinding(code='SWEPT_UNRESOLVED',message=f'Conservative {kind} swept volumes overlap ({link} {other}); motion is not certified',robot_id=rid,task_id=mid['active_steps'].get(rid),time=mid['time']));return False
        budget[0]+=1
        return check(a,mid,depth+1) and check(mid,b,depth+1)
    success=True
    for a,b in zip(frames,frames[1:]):
        if not check(a,b):success=False;break
    return findings,success and not findings
