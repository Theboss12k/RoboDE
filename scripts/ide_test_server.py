"""Disposable local IDE fixture; never bind or modify the user's runtime."""
from pathlib import Path
import shutil,tempfile,copy
import yaml
import uvicorn
from services.api.storage import Storage
from services.api.main import create_app
from services.validation.registry import ROOT

with tempfile.TemporaryDirectory(prefix='robot-ide-e2e-') as directory:
    root=Path(directory).resolve()
    shutil.copytree(ROOT/'examples/projects',root/'projects')
    project_path=root/'projects/apple_transfer/project.yaml'
    project=yaml.safe_load(project_path.read_text())
    second=copy.deepcopy(yaml.safe_load((root/'projects/apple_transfer/robots/arm_01/instance.yaml').read_text()))
    second['instance']={'id':'arm_02','name':'Atlas / Arm 02'}
    second['base_pose']={'x':0.,'y':1.3,'z':0.,'yaw':0.}
    folder=root/'projects/apple_transfer/robots/arm_02';folder.mkdir(parents=True,exist_ok=True)
    (folder/'instance.yaml').write_text(yaml.safe_dump(second))
    project['robots'].append('robots/arm_02/instance.yaml');project_path.write_text(yaml.safe_dump(project))
    uvicorn.run(create_app(Storage(root),speed=1),host='127.0.0.1',port=8877)
