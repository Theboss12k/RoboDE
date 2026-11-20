"""Disposable evaluation projects, shared by the eval suite and scripts/local_model_evaluation_server.py."""
import copy
from pathlib import Path
import shutil
import yaml

# The demo arm's instance pose; every case starts from it, so "unchanged" is checked against these values.
INITIAL_JOINTS = {'base_yaw':0.0,'shoulder':1.0,'elbow':-1.8,'wrist':0.8,'gripper':0.08}
ROBOT_NAMES = {'arm_01':'ARM ONE','arm_02':'ARM TWO'}
BASE_OFFSETS = {'arm_01':(0.,0.,0.),'arm_02':(0.,1.3,0.)}


def make_two_arm_project(root: Path, pid: str, name: str | None = None) -> Path:
    """ARM ONE at the origin and ARM TWO 1.3 m away, in the apple_transfer scene, simulated with the mock adapter."""
    from services.validation.registry import ROOT
    target = Path(root)/'projects'/pid
    target.mkdir(parents=True)
    for sub in ('robots','environment'):
        shutil.copytree(ROOT/'examples/projects/apple_transfer'/sub, target/sub)
    initial = yaml.safe_load((ROOT/'robot_system/registry/models/demo_arm/instances/instance.yaml').read_text())
    for rid, label in ROBOT_NAMES.items():
        instance = copy.deepcopy(initial)
        instance['instance'] = {'id':rid,'name':label}
        x, y, z = BASE_OFFSETS[rid]
        instance['base_pose'] = {'x':x,'y':y,'z':z,'yaw':0.}
        folder = target/'robots'/rid
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'instance.yaml').write_text(yaml.safe_dump(instance))
    project = yaml.safe_load((ROOT/'examples/projects/apple_transfer/project.yaml').read_text())
    project.update(id=pid, name=name or 'Evaluation · '+pid, robots=[f'robots/{rid}/instance.yaml' for rid in ROBOT_NAMES], simulation={'adapter':'mock'})
    project.pop('default_goals', None)
    project.pop('workflow_tasks', None)
    (target/'project.yaml').write_text(yaml.safe_dump(project))
    return target
