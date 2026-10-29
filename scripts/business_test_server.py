"""Isolated business browser-test runtime; never writes to saved user projects."""
import shutil
import tempfile
from pathlib import Path
import yaml
import uvicorn
from services.api.storage import Storage
from services.api.main import create_app
from services.validation.registry import ROOT

with tempfile.TemporaryDirectory(prefix='robot-business-test-') as directory:
    root=Path(directory);target=root/'projects/apple_transfer';target.mkdir(parents=True)
    for name in ('robots','environment'):shutil.copytree(ROOT/'examples/projects/apple_transfer'/name,target/name)
    project=yaml.safe_load((ROOT/'examples/projects/apple_transfer/project.yaml').read_text())
    project.update(robots=['robots/arm_01/instance.yaml'],simulation={'adapter':'mock'})
    project.pop('workflow_tasks',None);project.pop('default_goals',None)
    (target/'project.yaml').write_text(yaml.safe_dump(project))
    shutil.copyfile(ROOT/'robot_system/registry/models/demo_arm/instances/instance.yaml',target/'robots/arm_01/instance.yaml')
    world={'objects':[dict(id='apple',name='Apple',kind='object',position=dict(x=.34,y=-.16,z=.0525),size=dict(x=.065,y=.065,z=.065),mass_kg=.08),dict(id='table1',name='Table1',kind='obstacle',position=dict(x=.34,y=-.16,z=.01),size=dict(x=.14,y=.14,z=.02),mass_kg=0),dict(id='table2',name='Table2',kind='obstacle',position=dict(x=.27,y=.27,z=.01),size=dict(x=.18,y=.18,z=.02),mass_kg=0)]}
    (target/'environment/world.yaml').write_text(yaml.safe_dump(world))
    uvicorn.run(create_app(Storage(root),speed=100),host='127.0.0.1',port=8876)
