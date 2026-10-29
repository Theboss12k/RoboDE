"""Project-instance connection settings are separate from reusable adapter code."""
import json
import re
import uuid
from urllib.parse import urlparse
from pydantic import Field
from shared.models.domain import Contract, now
from services.api.storage import atomic_json,safe_id


class ProfileRequest(Contract):
    name:str=Field(min_length=1,max_length=100)
    adapter_id:str
    connection:dict[str,str]


def profile_path(store,project_id,robot_id):
    _,instances,_,_=store.load_project(project_id)
    if robot_id not in {i['instance']['id'] for i in instances}:
        raise ValueError('Unknown project robot instance')
    return store.project_folder(project_id)/'robots'/safe_id(robot_id)/'connections.json'


def list_profiles(store,project_id,robot_id):
    path=profile_path(store,project_id,robot_id)
    return json.loads(path.read_text()) if path.exists() else []


def get_profile(store,project_id,robot_id,profile_id):
    profile=next((p for p in list_profiles(store,project_id,robot_id) if p['id']==profile_id),None)
    if profile is None:
        raise ValueError('Connection profile not found for this project robot')
    return profile


def save_profile(store,registry,project_id,robot_id,data,profile_id=None):
    bundle=registry.get(data.adapter_id)
    instances=store.load_project(project_id)[1]
    instance=next(i for i in instances if i['instance']['id']==robot_id)
    if instance['robot_model']['id']!=bundle['model_id']:
        raise ValueError('Connection profile adapter belongs to a different robot model')
    if any(re.search(r'password|secret|api_key|^token$',key,re.I) for key in data.connection):
        raise ValueError('Use environment variable references for credentials')
    if bundle['kind']=='ros2':
        parsed=urlparse(data.connection.get('bridge_url',''))
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Provide an HTTP(S) bridge URL without embedded credentials')
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',data.connection.get('token_env','ROS_BRIDGE_TOKEN')):
            raise ValueError('Provide a token environment variable name')
    profiles=list_profiles(store,project_id,robot_id)
    if profile_id and profile_id not in {p['id'] for p in profiles}:
        raise ValueError('Connection profile not found')
    profile={'id':profile_id or uuid.uuid4().hex[:12],'name':data.name.strip(),'adapter_id':bundle['id'],
             'adapter_hash':bundle['hash'],'connection':data.connection,'updated_at':now()}
    if not profile['name']:
        raise ValueError('Connection profile name cannot be blank')
    atomic_json(profile_path(store,project_id,robot_id),[p for p in profiles if p['id']!=profile['id']]+[profile])
    return profile
