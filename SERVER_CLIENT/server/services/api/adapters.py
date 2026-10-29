from shared.models.command import StandardCommand
"""Adapter drafting, review, testing and explicit manual control endpoints."""
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import StrictFloat
from shared.models.domain import Contract
from services.adapters.generation import GenerateAdapter
import httpx
from services.adapters.profiles import ProfileRequest,list_profiles,save_profile
from services.api.configuration import Placement

class Preview(Contract):
    positions: dict[str,StrictFloat]
    base_pose: Placement

class Review(Contract):
    expected_hash: str

class OpenControls(Contract):
    robot_id: str
    adapter_id: str
    mode: Literal['test','environment','live'] = 'test'
    profile_id: str | None = None
    preview: Preview | None = None

class NamedCommand(Contract):
    command_id: str
    arguments: dict[str,StrictFloat] = {}

class Command(Contract):
    positions: dict[str,StrictFloat]


def adapters_router(registry,controls,controller):
    router = APIRouter(prefix='/api')

    @router.get('/models/{model_id}/adapters')
    async def list_adapters(model_id:str):
        return registry.list(model_id)

    @router.post('/projects/{project_id}/adapters/discover-commands')
    async def discover(project_id:str,data:GenerateAdapter):
        instances=controller.storage.load_project(project_id)[1]
        instance=next((i for i in instances if i['robot_model']['id']==data.model_id),None)
        if instance is None:raise ValueError('Add a project instance of the selected model first')
        return {'commands':await registry.discover(data,instance['initial_configuration']['actuator_positions'])}

    @router.post('/projects/{project_id}/adapters/generate',status_code=201)
    async def generate(project_id:str,data:GenerateAdapter):
        instances = controller.storage.load_project(project_id)[1]
        instance = next((i for i in instances if i['robot_model']['id']==data.model_id),None)
        if instance is None:
            raise ValueError('Add a project instance of this model before generating its adapter')
        try:
            return await registry.generate(data,instance['initial_configuration']['actuator_positions'])
        except (httpx.HTTPError,KeyError,TypeError) as error:
            raise HTTPException(502,'SDK drafting provider failed; no adapter was activated') from error

    @router.get('/projects/{project_id}/robots/{robot_id}/connections')
    async def profiles(project_id:str,robot_id:str):
        return list_profiles(registry.store,project_id,robot_id)

    @router.post('/projects/{project_id}/robots/{robot_id}/connections',status_code=201)
    async def create_profile(project_id:str,robot_id:str,data:ProfileRequest):
        return save_profile(registry.store,registry,project_id,robot_id,data)

    @router.put('/projects/{project_id}/robots/{robot_id}/connections/{profile_id}')
    async def update_profile(project_id:str,robot_id:str,profile_id:str,data:ProfileRequest):
        if any(s['project_id']==project_id and s['robot_id']==robot_id and s.get('profile_id')==profile_id for s in controls.sessions.values()):
            raise ValueError('Disconnect controls before changing their connection profile')
        return save_profile(registry.store,registry,project_id,robot_id,data,profile_id)

    @router.get('/adapters/{adapter_id}')
    async def get(adapter_id:str):
        return registry.get(adapter_id)

    @router.post('/adapters/{adapter_id}/review')
    async def review(adapter_id:str,data:Review):
        return registry.review(adapter_id,data.expected_hash)

    @router.post('/adapters/{adapter_id}/test')
    async def test(adapter_id:str):
        return await registry.test(adapter_id)

    @router.post('/projects/{project_id}/controls',status_code=201)
    async def open_controls(project_id:str,data:OpenControls):
        return await controls.open(project_id,data.robot_id,data.adapter_id,data.mode,data.profile_id,
            data.preview.model_dump() if data.preview else None)

    @router.put('/controls/{session_id}/preview-base')
    async def preview_base(session_id:str,data:Placement):
        return await controls.preview_base(session_id,data.model_dump())

    @router.get('/controls/{session_id}/tool-poses')
    async def tool_poses(session_id:str):
        s=controls.get(session_id)
        feedback=(await controls.read(session_id))['feedback']
        from services.planning.kinematics import with_base,forward
        from services.commands.standard import effectors
        _,instances,models,_=controls.context(s)
        index=next(n for n,i in enumerate(instances) if i['instance']['id']==s['robot_id'])
        instance=instances[index]
        if 'preview_base' in s:instance={**instance,'base_pose':s['preview_base']}
        model=with_base(models[index],instance)
        result={}
        for target in effectors(model):
            if model['kinematics']['solver']=='serial_chain_dls_v1':
                from services.planning.serial_ik import effector_frame
                t=effector_frame(model,feedback['positions'],target)
                position=[row[3] for row in t[:3]]
            else:
                pose=forward(model,feedback['positions'])
                position=[pose.x,pose.y,pose.z]
            result[target]=position
        return {'frame':model['kinematics']['world_frame'],'positions':result}

    @router.get('/controls/{session_id}')
    async def read(session_id:str):
        return await controls.read(session_id)

    @router.post('/controls/{session_id}/validate')
    async def validate(session_id:str):
        return await controls.validate(session_id)

    @router.post('/controls/{session_id}/arm')
    async def arm(session_id:str):
        return await controls.arm(session_id)

    @router.post('/controls/{session_id}/command')
    async def command(session_id:str,data:Command):
        return await controls.command(session_id,data.positions)

    @router.post('/controls/{session_id}/standard-command')
    async def standard_command(session_id:str,data:StandardCommand):
        return await controls.command(session_id,standard_command=data)

    @router.post('/controls/{session_id}/named-command',status_code=202)
    async def named_command(session_id:str,data:NamedCommand):
        return await controls.named_command(session_id,data.command_id,data.arguments)

    @router.post('/controls/{session_id}/stop')
    async def stop(session_id:str):
        return await controls.stop(session_id)

    @router.delete('/controls/{session_id}')
    async def close(session_id:str):
        return await controls.close_session(session_id)

    return router
