import shutil
import pytest
import yaml
from services.api.storage import Storage
from services.validation.registry import ROOT


@pytest.fixture
def store(tmp_path):
    source = ROOT / "examples/projects/apple_transfer"
    target = tmp_path / "projects/apple_transfer"
    target.mkdir(parents=True)
    shutil.copyfile(source / "project.yaml", target / "project.yaml")
    shutil.copytree(source / "robots", target / "robots")
    shutil.copytree(source / "environment", target / "environment")
    project = yaml.safe_load((target / "project.yaml").read_text())
    project["robots"] = ["robots/arm_01/instance.yaml"]
    project["simulation"] = {"adapter":"mock"}
    project.pop("workflow_tasks",None)
    project.pop("default_goals",None)
    (target / "project.yaml").write_text(yaml.safe_dump(project))
    shutil.copyfile(ROOT / "robot_system/registry/models/demo_arm/instances/instance.yaml",target / "robots/arm_01/instance.yaml")
    store = Storage(tmp_path)
    # Contract tests attach to an injected worker, independent of host OS defaults.
    from services.api.storage import atomic_json
    atomic_json(store.runtime/'connections/isaac.json', {'deployment':'remote'})
    return store


@pytest.fixture
def model():
    from services.validation.registry import MODEL_ROOT, load_model
    return load_model(MODEL_ROOT / "demo_arm")


@pytest.fixture
def instance(model):
    from services.validation.registry import MODEL_ROOT, load_instance
    return load_instance(MODEL_ROOT / "demo_arm/instances/instance.yaml", model)
