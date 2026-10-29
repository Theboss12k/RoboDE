"""Optional ROS 2 Jazzy bridge. Run with the ROS environment's Python, not Electron.
Uses monitored FollowJointTrajectory actions for the arm and optional gripper.
The deployment must supply real joint limits and a stable hardware device ID.
"""
import argparse
import asyncio
import hmac
import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict


class Motion(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False)
    positions: dict[str,float]
    duration: float


class ROSController:
    def __init__(self,device_id,joints,arm_action,joint_states,gripper_action='',gripper_joint=''):
        import rclpy
        from rclpy.action import ActionClient
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
        from sensor_msgs.msg import JointState
        from control_msgs.action import FollowJointTrajectory
        self.rclpy,self.action_type = rclpy,FollowJointTrajectory
        rclpy.init()
        self.node = Node('robot_ide_manual_bridge')
        self.executor = MultiThreadedExecutor()
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin,daemon=True)
        self.device_id,self.joints = device_id,joints
        self.gripper_joint = gripper_joint
        if bool(gripper_action) != bool(gripper_joint) or (gripper_joint and gripper_joint not in joints):
            raise ValueError('Gripper action and a registered gripper joint must be supplied together')
        self.arm = ActionClient(self.node,FollowJointTrajectory,arm_action)
        self.gripper = ActionClient(self.node,FollowJointTrajectory,gripper_action) if gripper_action else None
        self.latest,self.measured,self.quiet_since = None,0.,None
        self.lock = threading.Lock()
        self.handles = []
        self.pending = False
        self.epoch = 0
        self.node.create_subscription(JointState,joint_states,self.observe,10)
        self.thread.start()

    def observe(self,message):
        try:
            index = {name:i for i,name in enumerate(message.name)}
            positions = {name:message.position[index[name]] for name in self.joints}
            velocities = {name:message.velocity[index[name]] for name in self.joints}
            stamp = message.header.stamp.sec + message.header.stamp.nanosec/1e9
            ros_now = self.node.get_clock().now().nanoseconds/1e9
            if not -.5 <= ros_now-stamp <= 1.5 or any(not math.isfinite(v) for v in [*positions.values(),*velocities.values()]):
                return
            quiet = all(abs(v)<=.005 for v in velocities.values())
            with self.lock:
                self.latest,self.measured = positions,time.monotonic()
                self.quiet_since = (self.quiet_since or self.measured) if quiet else None
        except (KeyError,IndexError):
            return

    def state(self):
        with self.lock:
            if self.latest is None or time.monotonic()-self.measured>1.5:
                raise ValueError('Missing or stale measured joint position/velocity feedback')
            result = {'positions':dict(self.latest),'stopped':bool(not self.pending and self.quiet_since and time.monotonic()-self.quiet_since>=.2),
                'measured_at':datetime.now(timezone.utc).isoformat(),'device_id':self.device_id,'connected':True,
                'ready':self.arm.server_is_ready() and (self.gripper is None or self.gripper.server_is_ready()),
                'stop_supported':True}
        return result

    async def future(self,future,timeout):
        deadline = time.monotonic()+timeout
        while not future.done():
            if time.monotonic()>deadline:
                raise TimeoutError('ROS controller response timed out')
            await asyncio.sleep(.01)
        return future.result()

    async def command(self,positions,duration):
        from trajectory_msgs.msg import JointTrajectoryPoint
        state = self.state()
        if not state['ready'] or self.pending or self.handles:
            raise ValueError('Controller is unavailable or already has an active command')
        if set(positions)!=set(self.joints) or not .5<=duration<=4:
            raise ValueError('Supply all joints and a bounded command duration')
        for name,value in positions.items():
            limits = self.joints[name]
            delta = abs(value-state['positions'][name])
            if not math.isfinite(value) or not limits['min']<=value<=limits['max']:
                raise ValueError('Joint position outside configured limits')
            if delta>(.15 if limits['unit']=='rad' else .01)+1e-9:
                raise ValueError('Manual increment exceeds bridge limit')
            if 1.95*delta/duration>limits['velocity'] or 6.2*delta/(duration*duration)>limits['acceleration']:
                raise ValueError('Command exceeds joint motion limits')
        self.pending = True
        epoch = self.epoch
        try:
            clients = [(self.arm,[name for name in self.joints if name!=self.gripper_joint])]
            if self.gripper:
                clients.append((self.gripper,[self.gripper_joint]))
            for client,names in clients:
                goal = self.action_type.Goal()
                goal.trajectory.joint_names = names
                for n in range(1,31):
                    t=n/30
                    blend=10*t**3-15*t**4+6*t**5
                    point=JointTrajectoryPoint()
                    point.positions=[state['positions'][name]+(positions[name]-state['positions'][name])*blend for name in names]
                    point.velocities=[(positions[name]-state['positions'][name])*(30*t*t-60*t**3+30*t**4)/duration for name in names]
                    nanos=round(duration*t*1e9)
                    point.time_from_start.sec,point.time_from_start.nanosec=divmod(nanos,1000000000)
                    goal.trajectory.points.append(point)
                handle=await self.future(client.send_goal_async(goal),1)
                if not handle.accepted:
                    raise ValueError('ROS controller rejected the trajectory')
                self.handles.append(handle)
                if epoch != self.epoch:
                    await self.future(handle.cancel_goal_async(),1)
                    raise ValueError('Command cancelled while awaiting controller acceptance')
            results=await asyncio.gather(*(self.future(h.get_result_async(),duration+1.5) for h in self.handles))
            if any(r.status!=4 or r.result.error_code!=0 for r in results):
                raise ValueError('ROS trajectory failed or was cancelled')
            await asyncio.sleep(.25)
            self.pending=False
            final=self.state()
            if any(abs(final['positions'][name]-value)>(.01 if self.joints[name]['unit']=='rad' else .003) for name,value in positions.items()):
                raise ValueError('Measured feedback did not reach the commanded target')
            return final
        except BaseException:
            await self.stop(wait_for_pending=False)
            raise
        finally:
            self.pending=False
            self.handles=[]

    async def stop(self,wait_for_pending=True):
        self.epoch += 1
        # A cancel acknowledgement is not measured stop confirmation.
        for handle in list(self.handles):
            await self.future(handle.cancel_goal_async(),1)
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            state=self.state()
            if state['stopped'] or not wait_for_pending:
                return state
            await asyncio.sleep(.05)
        return self.state()

    def close(self):
        self.executor.shutdown()
        self.node.destroy_node()
        self.rclpy.shutdown()


def create_bridge(controller,token,lease_timeout=5):
    if len(token)<16:
        raise ValueError('ROS_BRIDGE_TOKEN must have at least 16 characters')
    from contextlib import asynccontextmanager
    owner,touched=None,0.

    @asynccontextmanager
    async def lifespan(app):
        async def watchdog():
            nonlocal owner
            while True:
                await asyncio.sleep(.25)
                if owner and time.monotonic()-touched>lease_timeout:
                    try:
                        state=await controller.stop()
                        if state['stopped']:
                            owner=None
                    except Exception:
                        pass  # Retain ownership while stop cannot be confirmed.
        job=asyncio.create_task(watchdog())
        yield
        job.cancel()
        try:
            await controller.stop()
        finally:
            controller.close()

    app=FastAPI(title='Robot IDE ROS 2 manual bridge',lifespan=lifespan)

    @app.middleware('http')
    async def auth(request:Request,call_next):
        from fastapi.responses import JSONResponse
        if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+token):
            return JSONResponse({'detail':'Unauthorized'},status_code=401)
        if request.headers.get('origin'):
            return JSONResponse({'detail':'Bridge is not a browser endpoint'},status_code=403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid(request,error):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':str(error)},status_code=422)

    def session(request,claim=False):
        nonlocal owner,touched
        key=request.headers.get('X-Control-Session','')
        if not key or len(key)>80:
            raise HTTPException(400,'Control session ID required')
        if claim:
            if owner not in {None,key}:
                raise HTTPException(409,'Physical controller is owned by another session')
            owner=key
        if key==owner:
            touched=time.monotonic()
        return key

    @app.post('/v1/state')
    async def state(request:Request):
        key=session(request)
        result=controller.state()
        if owner not in {None,key}:
            result['ready']=False
        return result

    @app.post('/v1/command')
    async def command(request:Request,data:Motion):
        key=session(request)
        if key!=owner:
            raise HTTPException(409,'Validate and claim this connection before commanding')
        return await controller.command(data.positions,data.duration)

    @app.post('/v1/stop')
    async def stop(request:Request):
        session(request,True)
        return await controller.stop()

    @app.post('/v1/disconnect')
    async def disconnect(request:Request):
        nonlocal owner
        key=session(request)
        if owner not in {None,key}:
            raise HTTPException(409,'Connection belongs to another session')
        result=await controller.stop()
        if result['stopped']:
            owner=None
        return result

    return app


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--device-id',required=True,help='Stable physical controller identity; use the same ID for every connection to this device')
    parser.add_argument('--joints',required=True,help='JSON file mapping controller joint names to min,max,velocity,acceleration,unit')
    parser.add_argument('--arm-action',default='/joint_trajectory_controller/follow_joint_trajectory')
    parser.add_argument('--joint-states',default='/joint_states')
    parser.add_argument('--gripper-action',default='')
    parser.add_argument('--gripper-joint',default='')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8767)
    args=parser.parse_args()
    joints=json.load(open(args.joints))
    if not joints or any(a['unit'] not in {'rad','m'} or not a['min']<a['max'] or a['velocity']<=0 or a['acceleration']<=0 for a in joints.values()):
        parser.error('Configure finite, positive controller joint limits in rad/m')
    controller=ROSController(args.device_id,joints,args.arm_action,args.joint_states,args.gripper_action,args.gripper_joint)
    import uvicorn
    uvicorn.run(create_bridge(controller,os.getenv('ROS_BRIDGE_TOKEN','')),host=args.host,port=args.port)

if __name__=='__main__':
    main()
