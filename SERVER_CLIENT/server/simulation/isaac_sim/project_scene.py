"""Build educational robot assets for automatic project scene transfer.

Manufacturer geometry always comes from the operator's approved catalog. These
generated demo articulations are labelled as educational, never manufacturer USD.
"""
import copy
import hashlib
import json
from pathlib import Path

from services.validation.registry import load_model,read_yaml
from services.planning.kinematics import with_base,supports_model
from simulation.isaac_sim.contracts import require_same_model


def prepare_robots(request,catalog,folder,store):
    from pxr import Usd
    from simulation.isaac_sim.build_demo_scene import build
    folder=Path(folder)
    additions={}
    for entry in request.robots:
        instance=entry['instance'];mid=instance['robot_model']['id']
        if mid in catalog.get('robots',{}) or mid in additions:continue
        model=load_model(store.model_folder(mid))
        require_same_model(entry['model'],with_base(model,instance),instance['instance']['id'])
        # The analytic demo has explicit authored link geometry. Other designs
        # need a real imported USD articulation, rather than guessed geometry.
        if mid!='demo_arm' or model['kinematics']['solver']!='analytic_yaw_two_link_v1' or not supports_model(model):
            raise ValueError(f'{mid}: configure its manufacturer USD and joint mapping once in the worker asset catalog; the scene will then transfer automatically')
        key=hashlib.sha256(json.dumps({'model':model,'generator_version':6},sort_keys=True).encode()).hexdigest()
        asset_folder=folder/key
        path=asset_folder/'cell.usda'
        if not path.exists():
            i=copy.deepcopy(instance);i['instance']['id']='robot'
            i['base_pose']={'x':0.,'y':0.,'z':0.,'yaw':0.}
            manifest=read_yaml(build(request.project_id,asset_folder,scene_data=({},[i],[model],[])))
            stage=Usd.Stage.Open(manifest['scene'])
            stage.RemovePrim('/World/Table');stage.RemovePrim('/World/Physics')
            stage.GetRootLayer().Save()
        additions[mid]={'usd':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'joints':{k:k for k in model['actuators']['actuators']},'articulation_path':'robot','provenance':'generated_educational_demo'}
    catalog.setdefault('robots',{}).update(additions)
