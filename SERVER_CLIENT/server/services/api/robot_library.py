"""Global robots/adapters and explicit project instance bindings, independent of projects."""
import copy
from pathlib import Path
from typing import Literal
import yaml
from fastapi import APIRouter,HTTPException
from pydantic import Field
from shared.models.domain import Contract,now
from services.adapters.generation import GenerateAdapter
from services.validation.registry import load_model,load_instance
from services.api.storage import safe_id

class AdapterChoice(Contract):
    adapter_id:str=Field(min_length=1,max_length=80)
    category:Literal['physical','virtual']='virtual'


def resolve_binding(registry,model_id,adapter_id='mock',category=None):
    load_model(registry.store.model_folder(model_id))
    if adapter_id in {'mock','isaac_sim'}:
        result={'adapter_id':adapter_id,'category':'virtual','adapter_hash':None}
    else:
        bundle=registry.get(adapter_id)
        if bundle['model_id']!=model_id:raise ValueError('Choose an adapter compatible with the selected global robot')
        if bundle['reviewed_hash']!=bundle['hash'] or not (bundle.get('test_report') or {}).get('passed'):
            raise ValueError('Review and pass global adapter tests before assigning it to a project')
        result={'adapter_id':adapter_id,'category':bundle['category'],'adapter_hash':bundle['hash']}
    if category and result['category']!=category:raise ValueError('Adapter does not match the physical/virtual target')
    return result


def robot_library_router(store,registry,controls,controller):
    router=APIRouter(prefix='/api')
    def definition(model_id):
        folder=store.model_folder(model_id);model=load_model(folder)
        instance=load_instance(folder/'instances/instance.yaml',model)
        return model,instance

    @router.get('/library/robots/{model_id}/preview')
    async def preview(model_id:str):
        from services.planning.kinematics import supports_model
        model,instance=definition(model_id);model={**model,'planning_supported':supports_model(model)}
        state={'instance_id':instance['instance']['id'],'positions':instance['initial_configuration']['actuator_positions'],
               'source':'simulation','measured_at':now(),'stopped':True,'connected':False}
        # An in-memory isolated scene; no project folder or project robot is created.
        return {'project':{'id':'library:'+model_id,'name':model['robot']['name'],'description':'Isolated global library preview','robots':[],'default_prompt':'','simulation':{'adapter':'mock'}},
                'robots':[{'instance':instance,'model':model,'state':state}],'instance':instance,'model':model,'state':state,
                'objects':[],'adapter':'mock','environment_connected':False,'worker':None,'fingerprint':None,
                'plans':[],'plan_definitions':[],'runs':[],'held_object':None,'active_run':None}

    @router.get('/library/adapters')
    async def library_adapters():
        return [bundle for model in store.models() for bundle in registry.list(model['robot']['id'])]

    @router.post('/library/robots/{model_id}/adapters/discover-commands')
    async def discover(model_id:str,data:GenerateAdapter):
        if model_id!=data.model_id:raise ValueError('Robot model does not match this library entry')
        _,instance=definition(model_id)
        return {'commands':await registry.discover(data,instance['initial_configuration']['actuator_positions'])}

    @router.post('/library/robots/{model_id}/adapters/generate',status_code=201)
    async def generate(model_id:str,data:GenerateAdapter):
        if model_id!=data.model_id:raise ValueError('Robot model does not match this library entry')
        _,instance=definition(model_id)
        import httpx
        try:return await registry.generate(data,instance['initial_configuration']['actuator_positions'])
        except (httpx.HTTPError,KeyError,TypeError) as error:raise HTTPException(502,'Adapter drafting failed; no adapter was activated') from error

    @router.post('/library/robots/{model_id}/controls',status_code=201)
    async def test_controls(model_id:str,data:AdapterChoice):
        # Category is checked even for a draft; this route can never arm/contact hardware.
        if data.adapter_id not in {'mock','isaac_sim'}:
            b=registry.get(data.adapter_id)
            if b['category']!=data.category:raise ValueError('Adapter does not match the selected target')
        elif data.category!='virtual':raise ValueError('Simulator adapters are virtual targets')
        return await controls.open_library(model_id,data.adapter_id)

    @router.put('/projects/{project_id}/robots/{robot_id}/adapter')
    async def assign(project_id:str,robot_id:str,data:AdapterChoice):
        controller.ensure_idle(project_id)
        if any(s['project_id']==project_id for s in controls.sessions.values()):raise ValueError('Disconnect project controls before changing its robot adapter')
        project,instances,models,_=store.load_project(project_id)
        index=next((n for n,i in enumerate(instances) if i['instance']['id']==robot_id),None)
        if index is None:raise ValueError('Unknown project robot instance')
        instance=copy.deepcopy(instances[index]);instance['control_adapter']=resolve_binding(registry,models[index]['robot']['id'],data.adapter_id,data.category)
        path=store.project_folder(project_id)/project['robots'][index]
        temporary=path.with_suffix('.binding.tmp')
        try:
            temporary.write_text(yaml.safe_dump(instance,sort_keys=False));load_instance(temporary,models[index]);temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)
        # Sessions cache the instance: refresh the reference without moving its joints.
        for cached in [controller.sessions.get(project_id), (controller.offline.get(project_id) or [None])[0]]:
            if cached:cached.instances[robot_id]=instance
        return {'instance':instance,'requires_recompile':True,'hardware_authorized':False}
    return router
