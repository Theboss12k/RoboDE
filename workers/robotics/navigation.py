"""Bounded Nav2 ComputePathToPose job with a generated static occupancy map."""
import json
import math
from pathlib import Path
import subprocess
import time
import uuid
import yaml


def path_with_nav2(model,base,goal,objects,folder):
    import rclpy
    from rclpy.action import ActionClient
    from lifecycle_msgs.srv import ChangeState
    from nav2_msgs.action import ComputePathToPose
    from geometry_msgs.msg import PoseStamped
    mobility=model['mobility'];bounds=mobility['navigation_bounds'];resolution=.03
    width=math.ceil((bounds[2]-bounds[0])/resolution);height=math.ceil((bounds[3]-bounds[1])/resolution)
    if width*height>1_000_000:raise ValueError('Navigation map exceeds one million cells')
    cells=bytearray([254])*(width*height)
    for obj in objects:
        if obj['kind']=='region':continue
        if obj.get('mesh'):raise ValueError('Navigation needs reviewed collision geometry for mesh assets')
        for y in range(max(0,int((obj['position']['y']-obj['size']['y']/2-bounds[1])/resolution)),min(height,math.ceil((obj['position']['y']+obj['size']['y']/2-bounds[1])/resolution))):
            for x in range(max(0,int((obj['position']['x']-obj['size']['x']/2-bounds[0])/resolution)),min(width,math.ceil((obj['position']['x']+obj['size']['x']/2-bounds[0])/resolution))):cells[(height-1-y)*width+x]=0
    (folder/'map.pgm').write_bytes(f'P5\n{width} {height}\n255\n'.encode()+cells)
    (folder/'map.yaml').write_text(yaml.safe_dump({'image':str(folder/'map.pgm'),'resolution':resolution,'origin':[bounds[0],bounds[1],0.],'negate':0,'occupied_thresh':.65,'free_thresh':.2}))
    namespace='robode_'+uuid.uuid4().hex[:8]
    config={'planner_server':{'ros__parameters':{'use_sim_time':False,'expected_planner_frequency':1.,'planner_plugins':['GridBased'],'GridBased':{'plugin':'nav2_navfn_planner::NavfnPlanner','tolerance':.03,'use_astar':True,'allow_unknown':False}}},
        'global_costmap':{'global_costmap':{'ros__parameters':{'use_sim_time':False,'global_frame':'map','robot_base_frame':'base_link','update_frequency':2.,'publish_frequency':1.,'resolution':resolution,'track_unknown_space':True,'footprint':json.dumps(mobility['footprint']),
        'plugins':['static_layer','inflation_layer'],'static_layer':{'plugin':'nav2_costmap_2d::StaticLayer','map_subscribe_transient_local':True,'map_topic':'map'},'inflation_layer':{'plugin':'nav2_costmap_2d::InflationLayer','cost_scaling_factor':3.,'inflation_radius':max(math.hypot(*p) for p in mobility['footprint'])+.05}}}}}
    (folder/'nav.yaml').write_text(yaml.safe_dump(config));processes=[]
    rclpy.init();node=rclpy.create_node('path_client',namespace=namespace)
    def launch(package,executable,*args):
        log=(folder/(executable+'.log')).open('wb');p=subprocess.Popen(['ros2','run',package,executable,*args,'--ros-args','-r','__ns:=/'+namespace],stdout=log,stderr=log);processes.append((p,log))
    def change(name,transition):
        client=node.create_client(ChangeState,name+'/change_state')
        if not client.wait_for_service(timeout_sec=10.):raise ValueError('Nav2 '+name+' lifecycle service did not start')
        request=ChangeState.Request();request.transition.id=transition;future=client.call_async(request);rclpy.spin_until_future_complete(node,future,timeout_sec=12.)
        if not future.done() or not future.result().success:raise ValueError('Nav2 '+name+' lifecycle transition failed')
    def pose(x,y,yaw):
        p=PoseStamped();p.header.frame_id='map';p.pose.position.x=float(x);p.pose.position.y=float(y);p.pose.orientation.z=math.sin(yaw/2);p.pose.orientation.w=math.cos(yaw/2);return p
    try:
        launch('tf2_ros','static_transform_publisher','--x',str(base.get('x',0)),'--y',str(base.get('y',0)),'--yaw',str(base.get('yaw',0)),'--frame-id','map','--child-frame-id','base_link')
        launch('nav2_map_server','map_server','--ros-args','-p','yaml_filename:='+str(folder/'map.yaml'),'-p','frame_id:=map')
        launch('nav2_planner','planner_server','--ros-args','--params-file',str(folder/'nav.yaml'))
        for name in ('map_server','planner_server'):change(name,1);change(name,3)
        action=ActionClient(node,ComputePathToPose,'compute_path_to_pose')
        if not action.wait_for_server(timeout_sec=10.):raise ValueError('Nav2 path planner unavailable')
        request=ComputePathToPose.Goal();request.start=pose(base.get('x',0),base.get('y',0),base.get('yaw',0));request.goal=pose(*goal['position'],goal.get('yaw',base.get('yaw',0)));request.use_start=True;request.planner_id='GridBased'
        future=action.send_goal_async(request);rclpy.spin_until_future_complete(node,future,timeout_sec=10.)
        if not future.done() or not future.result().accepted:raise ValueError('Nav2 rejected the navigation goal')
        result=future.result().get_result_async();rclpy.spin_until_future_complete(node,result,timeout_sec=15.)
        if not result.done() or result.result().status!=4 or not result.result().result.path.poses:raise ValueError('Nav2 found no navigation path within the configured boundaries')
        return [[p.pose.position.x,p.pose.position.y] for p in result.result().result.path.poses]
    finally:
        node.destroy_node();rclpy.shutdown()
        for p,log in processes:
            p.terminate()
            try:p.wait(timeout=2)
            except subprocess.TimeoutExpired:p.kill();p.wait()
            log.close()


def navigation_samples(model,q,base,goal,objects,folder):
    points=path_with_nav2(model,base,goal,objects,folder);m=model['mobility'];samples=[{'time':0.,'positions':dict(q),'base_pose':dict(base)}];clock=0.
    wheels=(m['left_wheel'],m['right_wheel']);radius=m['wheel_radius_m'];track=m['track_width_m'];pose=dict(base);positions=dict(q)
    def segment(distance,angle):
        nonlocal clock,pose,positions
        if abs(distance)+abs(angle)<1e-8:return
        travel={w:(distance+sign*angle*track/2)/radius for w,sign in zip(wheels,(-1,1))}
        duration=max(.2,1.95*abs(distance)/m['max_linear_m_s'],1.95*abs(angle)/m['max_angular_rad_s'])
        for w,d in travel.items():
            a=model['actuators']['actuators'][w];duration=max(duration,1.95*abs(d)/a['velocity'],math.sqrt(6.2*abs(d)/a['acceleration']))
        count=max(2,math.ceil(duration*30));duration=count/30
        for n in range(1,count+1):
            t=n/count;s=10*t**3-15*t**4+6*t**5;p=dict(pose);p['x']=pose.get('x',0)+distance*s*math.cos(pose.get('yaw',0));p['y']=pose.get('y',0)+distance*s*math.sin(pose.get('yaw',0));p['yaw']=pose.get('yaw',0)+angle*s
            samples.append({'time':clock+n/30,'positions':{**positions,**{w:positions[w]+travel[w]*s for w in wheels}},'base_pose':p})
        clock+=duration;pose=samples[-1]['base_pose'];positions=samples[-1]['positions']
    for point in points[1:]:
        dx,dy=point[0]-pose.get('x',0),point[1]-pose.get('y',0);distance=math.hypot(dx,dy)
        if distance<1e-6:continue
        heading=math.atan2(dy,dx);segment(0,math.atan2(math.sin(heading-pose.get('yaw',0)),math.cos(heading-pose.get('yaw',0))));segment(distance,0)
    segment(0,math.atan2(math.sin(goal.get('yaw',pose['yaw'])-pose['yaw']),math.cos(goal.get('yaw',pose['yaw'])-pose['yaw'])))
    return {'samples':samples,'engine':'Nav2/Navfn differential-drive','hardware_validated':False}
