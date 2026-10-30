"""Native MoveIt FK, numerical IK, OMPL and per-job PlanningScene checks.

No hardware connection is created by this module. Unknown checking coverage is
an incomplete report, not a successful physical validation.
"""
import base64
import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET
import numpy as np
from shared.models.robotics import ValidationReport,ValidationFinding
from services.planning.compiler_v2 import preview_goal
from services.validation.registry import validate_positions


def materialize(payload,folder):
    folder.mkdir(parents=True,exist_ok=True)
    files=payload.get('files',{})
    if len(files)>2048:raise ValueError('Robot package contains too many files')
    total=0
    for name,encoded in files.items():
        p=(folder/name).resolve()
        if not p.is_relative_to(folder.resolve()) or len(name)>512:raise ValueError('Invalid robot package path')
        raw=base64.b64decode(encoded,validate=True);total+=len(raw)
        if total>100*1024*1024:raise ValueError('Robot package exceeds 100 MB')
        p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    if not payload.get('urdf_path'):raise ValueError('Retained URDF collision geometry required; declarative preview links cannot qualify physical motion')
    p=(folder/payload['urdf_path']).resolve()
    if not p.is_relative_to(folder.resolve()):raise ValueError('Invalid URDF path')
    text=p.read_text()
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('URDF entities are unavailable')
    import hashlib
    if hashlib.sha256(p.read_bytes()).hexdigest()!=payload['model']['source_import']['sha256']:raise ValueError('URDF changed after review')
    root=ET.fromstring(text)
    meshes={m['uri']:m for m in payload['model'].get('source_import',{}).get('meshes',[])}
    for node in root.findall('.//mesh'):
        item=meshes.get(node.get('filename'))
        if not item or item['status']!='retained':raise ValueError('Every collision mesh must be included in the URDF package')
        mesh=(folder/item['path']).resolve()
        if not mesh.is_relative_to(folder.resolve()) or not mesh.is_file():raise ValueError('Missing retained mesh')
        if hashlib.sha256(mesh.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Collision mesh changed after review')
        node.set('filename',mesh.as_uri())
    # Virtual world anchor uses the same frame and base pose as the project.
    links={n.get('name') for n in root.findall('link')};children={n.find('child').get('link') for n in root.findall('joint')}
    base=next(iter(links-children));world='robode_world'
    ET.SubElement(root,'link',name=world)
    parent=world
    for name,kind,axis,child in [('robode_x','prismatic','1 0 0','robode_x_link'),('robode_y','prismatic','0 1 0','robode_y_link'),('robode_z','prismatic','0 0 1','robode_z_link'),('robode_yaw','revolute','0 0 1',base)]:
        if child!=base:ET.SubElement(root,'link',name=child)
        joint=ET.SubElement(root,'joint',name=name,type=kind);ET.SubElement(joint,'parent',link=parent);ET.SubElement(joint,'child',link=child);ET.SubElement(joint,'axis',xyz=axis);ET.SubElement(joint,'limit',lower='-100000',upper='100000',effort='1',velocity='100');parent=child
    return root,ET.tostring(root,encoding='unicode'),world


def srdf_config(root,model):
    robot=ET.Element('robot',name=root.get('name'))
    actuators=model['actuators']['actuators'];group=ET.SubElement(robot,'group',name='all_joints')
    for name in actuators:ET.SubElement(group,'joint',name=name)
    kinematics={};tool_groups={}
    parent={j.find('child').get('link'):j for j in root.findall('joint')}
    for name,tool in model['kinematics'].get('end_effectors',{}).items():
        link=tool['link'];chain=[];cursor=link
        while cursor in parent:
            j=parent[cursor];chain.append(j);cursor=j.find('parent').get('link')
        moving=[j for j in reversed(chain) if j.get('type')!='fixed' and not j.get('name','').startswith('robode_')]
        if not moving:continue
        base=moving[0].find('parent').get('link');gid='tool_'+name
        g=ET.SubElement(robot,'group',name=gid);ET.SubElement(g,'chain',base_link=base,tip_link=link)
        kinematics[gid]={'kinematics_solver':'kdl_kinematics_plugin/KDLKinematicsPlugin','kinematics_solver_search_resolution':.005,'kinematics_solver_timeout':.1}
        tool_groups[name]=gid
    # Only directly adjacent links may contact by construction. Other contacts
    # are never disabled automatically.
    for j in root.findall('joint'):
        ET.SubElement(robot,'disable_collisions',link1=j.find('parent').get('link'),link2=j.find('child').get('link'),reason='Adjacent')
    return ET.tostring(robot,encoding='unicode'),kinematics,tool_groups


_ENGINES=[]  # Keep C++ plugin owners alive until this isolated job exits.

class Engine:
    def __init__(self,payload,folder):
        _ENGINES.append(self)
        from moveit.planning import MoveItPy
        from moveit.core.robot_state import RobotState
        self.payload=payload;self.model=payload['model'];self.root,urdf,self.world=materialize(payload,folder)
        srdf,kinematics,self.groups=srdf_config(self.root,self.model)
        limits={key:{'has_velocity_limits':True,'max_velocity':float(a['velocity']),'has_acceleration_limits':True,'max_acceleration':float(a['acceleration'])} for key,a in self.model['actuators']['actuators'].items()}
        config={'robot_description':urdf,'allow_trajectory_execution':False,'robot_description_semantic':srdf,'robot_description_kinematics':kinematics,
            'robot_description_planning':{'joint_limits':limits},'planning_pipelines':{'pipeline_names':['ompl']},
            'ompl':{'planning_plugins':['ompl_interface/OMPLPlanner'],'request_adapters':['default_planning_request_adapters/ResolveConstraintFrames','default_planning_request_adapters/ValidateWorkspaceBounds','default_planning_request_adapters/CheckStartStateBounds','default_planning_request_adapters/CheckStartStateCollision'],
                'response_adapters':['default_planning_response_adapters/AddTimeOptimalParameterization','default_planning_response_adapters/ValidateSolution'],
                'planner_configs':{'RRTConnectkConfigDefault':{'type':'geometric::RRTConnect','range':0.0}},'all_joints':{'planner_configs':['RRTConnectkConfigDefault']},**{g:{'planner_configs':['RRTConnectkConfigDefault']} for g in self.groups.values()}},
            'plan_request_params':{'planning_attempts':1,'planning_pipeline':'ompl','planning_time':3.0,'max_velocity_scaling_factor':.5,'max_acceleration_scaling_factor':.5},
            'planning_scene_monitor_options':{'name':'robode_scene','robot_description':'robot_description','joint_state_topic':'/unused_joint_states','attached_collision_object_topic':'/unused_attached','publish_planning_scene_topic':'/unused_scene','monitored_planning_scene_topic':'/unused_monitored','wait_for_initial_state_timeout':0.0}}
        self.robot=MoveItPy(node_name='robode_motion',config_dict=config,provide_planning_service=False)
        self.robot_model=self.robot.get_robot_model();self.state=RobotState(self.robot_model)
        self.state.set_to_default_values();self.scene=self.robot.get_planning_scene_monitor();self.coverage=[]
    def state_for(self,q,base=None):
        base=base or self.model.get('base_pose',{});self.state.joint_positions={**q,**{'robode_'+name:base.get(key,0.) for name,key in [('x','x'),('y','y'),('z','z'),('yaw','yaw')]}};self.state.update();return self.state
    def apply_objects(self,objects):
        from moveit_msgs.msg import CollisionObject
        from shape_msgs.msg import SolidPrimitive
        from geometry_msgs.msg import Pose
        with self.scene.read_write() as scene:
            for obj in objects:
                if obj['kind']=='region':continue
                if obj.get('mesh'):raise ValueError('Imported environment mesh collision coverage is not configured; use reviewed collision primitives')
                item=CollisionObject();item.id=obj['id'];item.header.frame_id=self.world
                shape=SolidPrimitive();shape.type=SolidPrimitive.BOX;shape.dimensions=[obj['size'][k] for k in ('x','y','z')]
                pose=Pose();pose.orientation.w=1.;pose.position.x=obj['position']['x'];pose.position.y=obj['position']['y'];pose.position.z=obj['position']['z']
                item.primitives=[shape];item.primitive_poses=[pose];item.operation=CollisionObject.ADD;scene.apply_collision_object(item)
    def collision(self,q,base=None):
        state=self.state_for(q,base)
        with self.scene.read_only() as scene:colliding=scene.is_state_colliding(state,'',False)
        self.failure_position=None
        if colliding:
            tool=next(iter(self.model['kinematics'].get('end_effectors',{}).values()),None)
            if tool:
                point=np.asarray(state.get_global_link_transform(tool['link']))@np.array([*tool.get('xyz',[0,0,0]),1.]);self.failure_position=[float(x) for x in point[:3]]
        return colliding
    def plan(self,q,base,goal,objects):
        self.apply_objects(objects);group='all_joints';start=self.state_for(q,base)
        from moveit.core.robot_state import RobotState
        target=RobotState(self.robot_model);target.set_to_default_values();target.joint_positions=start.joint_positions
        if goal['kind']=='joint':target.joint_positions={**q,goal['joint']:goal['value']}
        elif goal['kind']=='configuration':target.joint_positions=goal['positions']
        elif goal['kind']=='tool':
            tool=self.model['kinematics']['end_effectors'][goal['target']];group=self.groups[goal['target']]
            from geometry_msgs.msg import Pose
            from scipy.spatial.transform import Rotation
            # Tool offsets and project base coordinates are included explicitly.
            desired=np.eye(4);desired[:3,3]=goal['position']
            if goal.get('orientation_rpy') is None:desired[:3,:3]=np.asarray(start.get_global_link_transform(tool['link']))[:3,:3]
            else:desired[:3,:3]=Rotation.from_euler('xyz',goal['orientation_rpy']).as_matrix()
            offset=np.eye(4);offset[:3,3]=tool.get('xyz',[0,0,0]);offset[:3,:3]=Rotation.from_euler('xyz',tool.get('rpy',[0,0,0])).as_matrix()
            desired=desired@np.linalg.inv(offset);p=Pose();p.position.x,p.position.y,p.position.z=map(float,desired[:3,3]);quat=Rotation.from_matrix(desired[:3,:3]).as_quat();p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w=map(float,quat)
            if not target.set_from_ik(group,p,tool['link'],.1):raise ValueError('IK found no valid configuration for this target')
        else:raise ValueError('Base MOVE requires a configured Nav2 navigation server')
        target.update();validate_positions(self.model,{k:target.joint_positions[k] for k in q})
        if all(abs(target.joint_positions[k]-q[k])<1e-9 for k in q):
            if self.collision(q,base):raise ValueError('Transit/hold configuration is in collision')
            return {'samples':[{'time':t,'positions':dict(q),'base_pose':base} for t in (0.,.1)],'engine':'MoveIt2 checked hold','hardware_validated':False}
        component=self.robot.get_planning_component(group);component.set_start_state(robot_state=start);component.set_goal_state(robot_state=target)
        result=component.plan()
        if not result:raise ValueError('MoveIt could not find a collision-free motion')
        message=result.trajectory.get_robot_trajectory_msg();traj=message.joint_trajectory;samples=[]
        for point in traj.points:
            positions={**q,**dict(zip(traj.joint_names,point.positions))}
            samples.append({'time':point.time_from_start.sec+point.time_from_start.nanosec/1e9,'positions':positions,'velocities':{**{k:0. for k in q},**dict(zip(traj.joint_names,point.velocities))},'base_pose':base})
        if len(samples)<2:raise ValueError('MoveIt returned an empty trajectory')
        return {'samples':samples,'engine':'MoveIt2/OMPL','hardware_validated':False}


def validate(body,folder):
    findings=[];coverage=['moveit_planning_scene','self_collision','environment_primitives'];incomplete=False
    frames=body['frames'];engines={}
    if any(o.get('mesh') for o in body['objects']):
        incomplete=True;findings.append(ValidationFinding(code='UNSUPPORTED_ASSET_GEOMETRY',message='Environment and carried-object mesh collision bounds need a reviewed native collision representation; use explicit collision primitives'))
    for rid,payload in body['robots'].items():
        try:
            robotfolder=folder/rid;robotfolder.mkdir()
            firstbase=frames[0].get('base_poses',{}).get(rid,payload['model'].get('base_pose',{}));payload=copy.deepcopy(payload);payload['model']['base_pose']=firstbase
            mapping=payload['model'].get('binding',{}).get('definition',{}).get('joints',[])
            metadata={j['name']:j for j in payload['model'].get('urdf_joint_metadata',[])}
            for joint in mapping:
                if joint['role']=='passive':
                    incomplete=True;findings.append(ValidationFinding(code='PASSIVE_COVERAGE',message='Passive joint motion is not constrained by a reviewed controller; physical checking is incomplete',robot_id=rid))
                if joint['role']=='coupled':
                    mimic=metadata.get(joint['joint_id'],{}).get('mimic')
                    if not mimic or mimic['joint']!=joint['coupled_to'] or abs(mimic.get('multiplier',1)-joint['multiplier'])>1e-9 or abs(mimic.get('offset',0)-joint['offset'])>1e-9:
                        incomplete=True;findings.append(ValidationFinding(code='COUPLING_COVERAGE',message='Mapped mechanical coupling must match the retained URDF mimic constraint for native physical checking',robot_id=rid))
            engine=Engine(payload,robotfolder)
            carried={oid for f in frames for oid in f.get('held_objects',{}).values() if oid}
            engine.apply_objects([o for o in body['objects'] if o['id'] not in carried]);engines[rid]=engine
            for frame in frames:


                if engine.collision(frame['robot_positions'][rid],frame.get('base_poses',{}).get(rid,firstbase)):
                    findings.append(ValidationFinding(code='COLLISION',message='MoveIt detects self-collision or environment collision (marker shows the tool pose)',position=engine.failure_position,robot_id=rid,task_id=frame.get('active_steps',{}).get(rid),time=frame['time']));break
        except Exception as error:
            incomplete=True;findings.append(ValidationFinding(code='GEOMETRY_COVERAGE',message=str(error),robot_id=rid))
    if len(engines)==len(body['robots']):
        from workers.robotics.swept import certify
        swept,complete=certify(engines,frames,body['objects']);findings.extend(swept);incomplete=incomplete or not complete
        if complete:coverage+=['conservative_swept_volumes','time_aligned_robots','carried_object_bounds']
    return ValidationReport(status='failed' if any(f.code=='COLLISION' for f in findings) else 'incomplete' if incomplete else 'passed',coverage=coverage,findings=findings,worker_revision='robotics-v2').model_dump(mode='json')


def main():
    request=json.loads(Path(sys.argv[1]).read_text());output=Path(sys.argv[2])
    try:
        with tempfile.TemporaryDirectory() as folder:
            if request['operation']=='validate':result=validate(request['body'],Path(folder))
            else:
                body=request['body'];payload=copy.deepcopy(body['robot']);payload['model']['base_pose']=body['base_pose']
                if body['goal']['kind']=='tool' and payload['model'].get('mobility',{}).get('classification')=='BOTH':
                    from workers.robotics.staged import plan_staged
                    result=plan_staged(payload,body['positions'],body['base_pose'],body['goal'],body['objects'],Path(folder))
                elif body['goal']['kind']=='base':
                    from workers.robotics.navigation import navigation_samples
                    result=navigation_samples(payload['model'],body['positions'],body['base_pose'],body['goal'],body['objects'],Path(folder))
                else:result=Engine(payload,Path(folder)).plan(body['positions'],body['base_pose'],body['goal'],body['objects'])
        output.write_text(json.dumps(result,allow_nan=False))
    except Exception as error:output.write_text(json.dumps({'error':str(error)}))
    # moveit_py owns executor/plugin threads. This per-job process never owns a
    # device; exit after the result is closed instead of unloading active C++ plugins.
    os._exit(0)
if __name__=='__main__':main()
