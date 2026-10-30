"""Isaac Sim 6.2 legacy Core API bridge. Import only after SimulationApp starts.

The deployment supplies a USD cell and a joint/object mapping. No predicted object
poses, ideal attachments, or joint teleportation are used while executing steps.
"""
import hashlib
import math
from pathlib import Path
import numpy as np
from shared.models.domain import RobotState, WorldObject, Pose, now
from simulation.isaac_sim.contracts import require_same_model,bounded_feedback,FEEDBACK_LIMIT_TOLERANCE
from services.api.storage import Storage
from services.planning.kinematics import with_base
from services.validation.registry import ROOT, MODEL_ROOT, load_model, load_instance, read_yaml


class NativeCell:
    def __init__(self,manifest_path):
        from isaacsim.core.api import World
        from isaacsim.core.prims import Articulation, RigidPrim, XFormPrim
        from isaacsim.core.utils.stage import open_stage
        self.manifest_path=Path(manifest_path)
        from isaacsim.core.version import get_version
        self.config = read_yaml(Path(manifest_path))
        self.mesh_assets=self.config.get('mesh_assets',{})
        self.scene_fault=None
        scene = Path(self.config['scene']).expanduser().resolve()
        if not scene.is_file():
            raise ValueError(f'USD cell not found: {scene}')
        digest = hashlib.sha256(scene.read_bytes()).hexdigest()
        if digest != self.config['scene_sha256']:
            raise ValueError('USD scene checksum differs from the deployment manifest')
        version = str(get_version()[0])
        if not version.startswith('6.2.'):
            raise ValueError(f'This bridge targets Isaac Sim 6.2.x, found {version}')
        open_stage(str(scene))
        self.dt = float(self.config.get('physics_dt',1/120))
        if not 0 < self.dt <= 1/60:
            raise ValueError('physics_dt must be positive and no larger than 1/60 s')
        self.world = World(stage_units_in_meters=1.,physics_dt=self.dt,rendering_dt=self.dt)
        self.models, self.instances, self.robots, self.indices, self.bases = {}, {}, {}, {}, {}
        catalog=Storage()
        for definition in self.config['robots']:
            instance = read_yaml(Path(definition['instance_file']))
            model = load_model(catalog.model_folder(instance['robot_model']['id']))
            if definition.get('model_snapshot'):
                from simulation.isaac_sim.robot_packages import reviewed_model
                model=reviewed_model(catalog,instance,definition['model_snapshot']);model.pop('base_pose',None)
            instance = load_instance(Path(definition['instance_file']),model)
            rid = instance['instance']['id']
            if rid in self.models:
                raise ValueError('Duplicate native robot instance')
            self.instances[rid], self.models[rid] = instance,with_base(model,instance)
            self.robots[rid] = self.world.scene.add(Articulation(prim_paths_expr=definition['prim_path'],name=rid))
            self.bases[rid] = definition
        self.objects = [WorldObject.model_validate(o) for o in self.config['objects']]
        self.object_views = {}
        for o in self.objects:
            path = self.config['object_prims'][o.id]
            cls = RigidPrim if o.kind == 'object' else XFormPrim
            self.object_views[o.id] = self.world.scene.add(cls(prim_paths_expr=path,name=f'object_{o.id}'))
        self.world.reset()
        for rid,robot in self.robots.items():
            robot.initialize()
            mapping = self.bases[rid]['joints']
            if set(mapping) != set(self.models[rid]['actuators']['actuators']):
                raise ValueError(f'{rid}: USD joint mapping must cover every model actuator')
            self.indices[rid] = np.array([robot.get_dof_index(mapping[k]) for k in self.models[rid]['actuators']['actuators']],dtype=np.int32)
            usd_limits = np.asarray(robot.get_dof_limits())[0]
            for key,index in zip(self.models[rid]['actuators']['actuators'],self.indices[rid]):
                spec = self.models[rid]['actuators']['actuators'][key]
                if spec['min'] < float(usd_limits[index][0])-.001 or spec['max'] > float(usd_limits[index][1])+.001:
                    raise ValueError(f'{rid}/{key}: model limits exceed the deployed USD articulation limits')
            position,orientation = robot.get_world_poses()
            expected = self.models[rid]['base_pose']
            if np.linalg.norm(position[0]-[expected[a] for a in ('x','y','z')]) > .002:
                raise ValueError(f'{rid}: USD robot base does not match project base pose')
            quaternion = np.asarray(orientation[0])
            target = np.array([math.cos(expected['yaw']/2),0,0,math.sin(expected['yaw']/2)])
            if min(np.linalg.norm(quaternion-target),np.linalg.norm(quaternion+target)) > .002:
                raise ValueError(f'{rid}: USD base rotation must match the Z-up project yaw')
        self.simulation_time = 0.
        from simulation.isaac_sim.grasp_feedback import ObservedGrasp
        self.grasp_tracker=ObservedGrasp()
        self.target_positions={rid:dict(zip(self.models[rid]['actuators']['actuators'],map(float,np.asarray(robot.get_joint_positions(joint_indices=self.indices[rid]))[0]))) for rid,robot in self.robots.items()}
        self.metadata = {'engine':'isaac_sim','simulator_version':version,'asset_sha256':digest,'physics_available':True,
                         'mobile_base_feedback':True,'attachment_feedback':True,'attachment_feedback_source':'observed_rigid_body_following_motion','collision_certificate':False,'joint_tracking_tolerance_rad':.12,'joint_tracking_tolerance_m':.015,
                         'feedback_limit_tolerance':FEEDBACK_LIMIT_TOLERANCE}

    def validate_scene(self,request):
        expected = {d['instance']['instance']['id']:d for d in request.robots}
        if set(expected) != set(self.models):
            raise ValueError('GPU USD cell robot IDs must exactly match the selected project')
        for rid,data in expected.items():
            if data['instance']['robot_model'] != self.instances[rid]['robot_model'] or data['instance'].get('base_pose',{'x':0.,'y':0.,'z':0.,'yaw':0.}) != self.models[rid]['base_pose']:
                raise ValueError(f'{rid}: worker model version or base pose differs from project')
            # Reject silently different limits, kinematics, units or control interfaces.
            require_same_model(data['model'],self.models[rid],rid)
        if {o.id for o in request.objects} != {o.id for o in self.objects}:
            raise ValueError('Worker object IDs differ from project')
        for item in request.objects:
            own = next(o for o in self.objects if o.id == item.id)
            if (item.kind,item.size,item.mass_kg) != (own.kind,own.size,own.mass_kg):
                raise ValueError(f'Object geometry or mass differs for {item.id}')

    def observe(self):
        if self.scene_fault:return {'states':{},'objects':[],'measured_at':now(),'simulation_time':self.simulation_time,'faults':[self.scene_fault]}
        stamp,states,corrections = now(),{},{}
        objects = []
        for item in self.objects:
            p,_ = self.object_views[item.id].get_world_poses()
            objects.append(item.model_copy(update={'position':Pose(x=float(p[0][0]),y=float(p[0][1]),z=float(p[0][2]))}).model_dump())
        for rid,robot in self.robots.items():
            q = np.asarray(robot.get_joint_positions(joint_indices=self.indices[rid]))[0]
            velocities = np.asarray(robot.get_joint_velocities(joint_indices=self.indices[rid]))[0]
            names = list(self.models[rid]['actuators']['actuators'])
            stopped = all(abs(float(v)) < (.002 if self.models[rid]['actuators']['actuators'][k]['unit']=='m' else .01) for k,v in zip(names,velocities))
            positions,adjusted=bounded_feedback(self.models[rid],dict(zip(names,map(float,q))))
            if adjusted:corrections[rid]=adjusted
            root_position,root_rotation=robot.get_world_poses();quat=root_rotation[0];w,x,y,z=map(float,quat);base_pose={'x':float(root_position[0][0]),'y':float(root_position[0][1]),'z':float(root_position[0][2]),'yaw':math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))}
            from services.commands.standard import effectors,components
            from services.planning.kinematics import forward
            component_map=components(self.models[rid]);attached={}
            for tool_id in effectors(self.models[rid]):
                definition=self.models[rid]['kinematics'].get('end_effectors',{}).get(tool_id,{})
                component=component_map.get(definition.get('component_id',tool_id)) or (next(iter(component_map.values())) if len(component_map)==1 and len(effectors(self.models[rid]))==1 else None)
                if not component:continue
                aperture=positions[component['actuator']];opening=(aperture-component['closed'])/(component['open']-component['closed']);closed=opening<.92
                point=forward({**self.models[rid],'base_pose':base_pose},positions,tool_id)
                observed=[{'id':o['id'],'position':[o['position'][k] for k in ('x','y','z')]} for o in objects if o['kind']=='object' and (self.models[rid]['actuators']['actuators'][component['actuator']]['unit']!='m' or aperture<=o['size']['x']+.003)]
                held=self.grasp_tracker.update((rid,tool_id),[point.x,point.y,point.z],observed,closed,self.simulation_time)
                if held:attached[tool_id]=held
            states[rid] = RobotState(instance_id=rid,positions=positions,source='simulation',measured_at=stamp,stopped=stopped,velocities=dict(zip(names,map(float,velocities))),base_pose=base_pose,attachments=list(attached.values()),attachment_tools=attached,attachment_source='simulation_observed_motion').model_dump()
        self.metadata['feedback_limit_corrections']={'measured_at':stamp,'robots':corrections}
        return {'states':states,'objects':objects,'measured_at':stamp,'simulation_time':self.simulation_time,'faults':[]}

    def inventory(self):
        import omni.usd
        from simulation.isaac_sim.inventory import scene_inventory
        return scene_inventory(omni.usd.get_context().get_stage(),self.models,self.instances,[WorldObject.model_validate(o) for o in self.observe()['objects']],
            {rid:data['prim_path'] for rid,data in self.bases.items()},self.config['object_prims'])

    def advance(self,positions,dt):
        if self.scene_fault:raise ValueError(self.scene_fault)
        count = round(dt/self.dt)
        if count < 1 or abs(count*self.dt-dt) > 1e-5:
            raise ValueError('Timeline sampling must be an integer multiple of worker physics_dt')
        for rid,q in positions.items():
            previous=self.target_positions.get(rid,q)
            # Follow the trajectory's motion instead of commanding zero desired
            # velocity at every moving waypoint. Targets remain force-driven.
            velocity=[max(-spec['velocity'],min(spec['velocity'],(q[k]-previous[k])/dt)) for k,spec in self.models[rid]['actuators']['actuators'].items()]
            self.robots[rid].set_joint_position_targets(np.array([[q[k] for k in self.models[rid]['actuators']['actuators']]]),joint_indices=self.indices[rid])
            self.robots[rid].set_joint_velocity_targets(np.array([velocity]),joint_indices=self.indices[rid])
            self.target_positions[rid]=dict(q)
        for _ in range(count):
            self.world.step(render=False)
            self.simulation_time += self.dt

    def stop(self):
        if self.scene_fault:
            # Scene edits can invalidate every tensor handle. Freeze the timeline
            # without querying those handles or claiming confirmed stopped feedback.
            self.world.pause()
            return
        targets = {rid:bounded_feedback(self.models[rid],dict(zip(self.models[rid]['actuators']['actuators'],map(float,np.asarray(robot.get_joint_positions(joint_indices=self.indices[rid]))[0]))))[0] for rid,robot in self.robots.items()}
        self.target_positions={rid:dict(q) for rid,q in targets.items()}
        # Hold observed positions with controller targets; never zero reported velocities.
        for _ in range(120):
            self.advance(targets,self.dt)
            if not self.scene_fault and all(s['stopped'] for s in self.observe()['states'].values()):
                return

    def sync_objects(self,objects):
        from simulation.isaac_sim.scene_assets import validate_objects,add_object
        from isaacsim.core.prims import RigidPrim,XFormPrim
        import omni.usd
        import yaml
        if self.scene_fault:raise ValueError(self.scene_fault)
        if not self.config.get('managed_objects'):raise ValueError('Object editing requires a managed scene')
        validate_objects(objects,self.mesh_assets)
        from simulation.isaac_sim.mesh_assets import geometry
        mesh_geometry={o.id:geometry(o,self.mesh_assets[o.mesh.asset_id]) for o in objects if o.mesh}
        try:
            stage=omni.usd.get_context().get_stage()
            # Removing a tracked rigid prim invalidates the whole PhysX tensor
            # view. Capture stopped joints before mutation and rebuild the physics
            # handles with those same joints as defaults, never the saved start.
            targets={rid:state['positions'] for rid,state in self.observe_robots().items()}
            for rid,q in targets.items():
                defaults=np.asarray(self.robots[rid].get_joint_positions()).copy()
                defaults[:,self.indices[rid]]=np.array([[q[k] for k in self.models[rid]['actuators']['actuators']]])
                self.robots[rid].set_joints_default_state(
                    positions=defaults,velocities=np.zeros_like(defaults))
            self.world.stop()
            for key in list(self.object_views):
                self.world.scene.remove_object('object_'+key,registry_only=True)
                stage.RemovePrim(self.config['object_prims'][key])
            paths={o.id:add_object(stage,o,mesh_geometry.get(o.id)) for o in objects}
            self.objects=[o.model_copy(deep=True) for o in objects];self.object_views={}
            for o in self.objects:
                cls=RigidPrim if o.kind=='object' else XFormPrim
                view=self.world.scene.add(cls(prim_paths_expr=paths[o.id],name='object_'+o.id))
                self.object_views[o.id]=view
            self.world.reset()
            self.config.update(objects=[o.model_dump() for o in objects],object_prims=paths,mesh_assets=self.mesh_assets)
            scene=Path(self.config['scene']);stage.GetRootLayer().Export(str(scene))
            self.config['scene_sha256']=hashlib.sha256(scene.read_bytes()).hexdigest()
            self.metadata['asset_sha256']=self.config['scene_sha256']
            self.manifest_path.write_text(yaml.safe_dump(self.config,sort_keys=False))
        except Exception as error:
            self.scene_fault='Native object update failed; reload the managed scene before continuing'
            self.stop()
            raise ValueError(self.scene_fault) from error

    def observe_robots(self):
        # Read joints independently while an object transaction replaces its views.
        result={}
        for rid,robot in self.robots.items():
            q=np.asarray(robot.get_joint_positions(joint_indices=self.indices[rid]))[0]
            positions,_=bounded_feedback(self.models[rid],dict(zip(self.models[rid]['actuators']['actuators'],map(float,q))))
            result[rid]={'positions':positions}
        return result

    def reset(self,positions,objects):
        if self.scene_fault:raise ValueError(self.scene_fault)
        if {o.id for o in objects} != {o.id for o in self.objects}:
            raise ValueError('Reset objects must match the deployed USD cell')
        # Reset and an explicit simulator scene hand-off initialize joint/object state.
        self.world.reset()
        for rid,q in positions.items():
            self.robots[rid].set_joint_positions(np.array([[q[k] for k in self.models[rid]['actuators']['actuators']]]),joint_indices=self.indices[rid])
            self.robots[rid].set_joint_velocities(np.zeros((1,len(q))),joint_indices=self.indices[rid])
        for item in objects:
            view = self.object_views[item.id]
            view.set_world_poses(positions=np.array([[item.position.x,item.position.y,item.position.z]]))
            if item.kind == 'object':
                view.set_linear_velocities(np.zeros((1,3)))
                view.set_angular_velocities(np.zeros((1,3)))
        self.simulation_time = 0.
        self.grasp_tracker.candidates.clear()
        self.target_positions={rid:dict(q) for rid,q in positions.items()}
        self.stop()
