"""Separate reusable BOT configuration from project environment placement."""
import copy
import math
import uuid
import yaml
from pydantic import StrictFloat
from fastapi import APIRouter
from shared.models.domain import Contract
from services.api.storage import atomic_json, safe_id
from services.validation.registry import MODEL_ROOT, load_model, load_instance, validate_positions

class Placement(Contract):
    x:float
    y:float
    z:float
    yaw:float

class ModelConfiguration(Contract):
    actuators:dict
    capabilities:dict

class StartingState(Contract):
    base_pose: Placement
    positions: dict[str,StrictFloat]
    expected_instance: dict
    expected_positions: dict[str,StrictFloat]


def configuration_router(store,controller,controls):
    router=APIRouter(prefix='/api')

    @router.put('/projects/{project_id}/robots/{robot_id}/starting-state')
    async def starting_state(project_id:str,robot_id:str,data:StartingState):
        """Commit a draft pose/configuration together, without rewriting past runs."""
        from shared.models.domain import Frame
        from services.execution.resources import environment_resource
        from services.planning.kinematics import with_base
        from services.planning.workflow import validate_cell
        from services.validation.trajectory import validate_trajectory
        from services.world_model.world import object_map
        if any(s['project_id']==project_id and s['robot_id']==robot_id for s in controls.sessions.values()):
            raise ValueError('Close robot controls before applying the starting point')
        controller.recordings.guard(project_id)
        controller.ensure_idle(project_id)
        project,instances,models,_=store.load_project(project_id)
        index=next((n for n,i in enumerate(instances) if i['instance']['id']==robot_id),None)
        if index is None:raise ValueError('Unknown project robot instance')
        if instances[index]!=data.expected_instance:raise ValueError('Robot configuration changed; reopen the robot editor')
        base=data.base_pose.model_dump()
        controls.check_base(base)
        if base['z']<0:raise ValueError('Robot base must be on or above the ground')
        validate_positions(models[index],data.positions)
        *_,cell,state=await controller.context(project_id,robot_id)
        owner='starting-state:'+uuid.uuid4().hex
        controller.resources.acquire([environment_resource(project_id,cell.backend)],owner)
        try:
            if state.positions!=data.expected_positions:raise ValueError('Robot state changed; reopen the robot editor')
            if any(cell.held_objects.values()):raise ValueError('Release held objects or reset the simulator before editing its starting point')
            states=await controller.states(cell)
            if states[robot_id].positions!=data.expected_positions:raise ValueError('Robot state changed; reopen the robot editor')
            if any(not s.stopped for s in states.values()):raise ValueError('Stop every robot before applying a starting point')
            updated=copy.deepcopy(instances[index])
            updated['base_pose']=base
            updated['initial_configuration']['actuator_positions']=data.positions
            target_models={**cell.models,robot_id:with_base(models[index],updated)}
            positions={rid:(data.positions if rid==robot_id else s.positions) for rid,s in states.items()}
            frames=[Frame(time=t,step_id='starting_point',positions=data.positions,robot_positions=positions,objects=object_map(cell.objects)) for t in (0.,.1)]
            validate_trajectory(target_models[robot_id],frames,cell.objects)
            validate_cell(frames,target_models,cell.objects)
            target_instances=[updated if n==index else i for n,i in enumerate(instances)]
            path=store.project_folder(project_id)/project['robots'][index]
            temporary=path.with_name('.starting-'+uuid.uuid4().hex+'.yaml')
            previous=path.read_text()
            previous_models,previous_instances=cell.models,cell.instances
            try:
                temporary.write_text(yaml.safe_dump(updated,sort_keys=False))
                load_instance(temporary,models[index])
                if cell.remote:
                    await cell.remote.reconfigure(target_instances,target_models,cell.objects,positions)
                else:
                    await cell.adapters[robot_id].command(data.positions)
                    await cell.adapters[robot_id].request_stop()
                temporary.replace(path)
                cell.instances={i['instance']['id']:i for i in target_instances}
                cell.models=target_models
                await controller.persist_state(project_id)
            except BaseException:
                path.write_text(previous)
                cell.models,cell.instances=previous_models,previous_instances
                if not cell.remote:
                    await cell.adapters[robot_id].command(state.positions)
                    await cell.adapters[robot_id].request_stop()
                else:
                    # Reload failure is surfaced; never claim the native scene rolled back.
                    controller.sessions.pop(project_id,None)
                    await cell.remote.disconnect()
                raise
            finally:
                temporary.unlink(missing_ok=True)
            return {'instance':updated,'applied':True,'source':'simulation','requires_recompile':True}
        finally:
            controller.resources.release(owner)

    @router.get('/projects/{project_id}/robots/{robot_id}/workspace')
    async def workspace(project_id:str,robot_id:str):
        from services.planning.kinematics import with_base
        from services.planning.workspace import reachable_workspace
        _,instances,models,_ = store.load_project(project_id)
        index = next((n for n,i in enumerate(instances) if i['instance']['id']==robot_id),None)
        if index is None:
            raise ValueError('Unknown project robot instance')
        instance = instances[index]
        return {'robot_id':robot_id,'name':instance['instance']['name'],
            **reachable_workspace(with_base(models[index],instance))}

    @router.put('/projects/{project_id}/robots/{robot_id}/placement')
    async def placement(project_id:str,robot_id:str,data:Placement):
        if any(s['project_id']==project_id and s['robot_id']==robot_id for s in controls.sessions.values()):raise ValueError('Disconnect robot controls before changing placement')
        controller.recordings.guard(project_id)
        controller.ensure_idle(project_id)
        project,instances,models,_=store.load_project(project_id)
        if project.get('simulation',{}).get('adapter','mock')!='mock':
            raise ValueError('Deploy matching USD geometry before changing Isaac Sim base placements')
        if any(not math.isfinite(v) for v in data.model_dump().values()):
            raise ValueError('Robot placement must be finite')
        index=next((i for i,v in enumerate(instances) if v['instance']['id']==robot_id),None)
        if index is None:
            raise ValueError('Unknown robot instance')
        path=store.project_folder(project_id)/project['robots'][index]
        previous=path.read_text()
        updated=copy.deepcopy(instances[index]);updated['base_pose']=data.model_dump()
        path.write_text(yaml.safe_dump(updated,sort_keys=False))
        try:
            load_instance(path,models[index])
        except BaseException:
            path.write_text(previous)
            raise
        return {'instance':updated,'actual_joint_state_unchanged':True}

    @router.put('/registry/{model_id}/configuration')
    async def configure_model(model_id:str,data:ModelConfiguration):
        if controller.resources.owners or controller.leases or controls.sessions:
            raise ValueError('Close controls and stop simulations before changing a reusable model')
        folder=store.model_folder(model_id)
        if folder.is_relative_to(MODEL_ROOT):
            import shutil
            destination=store.runtime/'imported_models'/model_id
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(folder,destination)
            folder=destination
        model=load_model(folder)
        paths=[folder/model['robot']['actuators'],folder/model['robot']['capabilities']]
        previous=[p.read_text() for p in paths]
        backup=store.runtime/'registry_backups'/model_id/uuid.uuid4().hex
        for path,text in zip(paths,previous):
            backup.mkdir(parents=True,exist_ok=True)
            (backup/path.name).write_text(text)
        try:
            for path,value in zip(paths,[{'actuators':data.actuators},data.capabilities]):
                path.write_text(yaml.safe_dump(value,sort_keys=False))
            result=load_model(folder)
            load_instance(folder/'instances/instance.yaml',result)
            # Shared model edits must keep every saved instance usable.
            for project in store.list_projects():
                _,instances,_,_=store.load_project(project['id'])
                for instance in instances:
                    if instance['robot_model']['id']==model_id:
                        validate_positions(result,instance['initial_configuration']['actuator_positions'])
        except BaseException:
            for path,text in zip(paths,previous):
                path.write_text(text)
            raise
        return result

    return router
