import copy
import math
import shutil
import pytest
import yaml
from services.validation.registry import MODEL_ROOT, load_model, load_instance, resolve_adapter, validate_positions


def test_model_and_instance_load(model, instance):
    assert model["robot"]["id"] == instance["robot_model"]["id"]
    assert "mock" in model["adapters"]


@pytest.mark.parametrize("name,value", [("missing_joint", 0), ("shoulder", 8), ("elbow", float("nan")), ("base_yaw", float("inf")), ("wrist", True)])
def test_invalid_actuators_and_values(model, instance, name, value):
    positions = dict(instance["initial_configuration"]["actuator_positions"])
    positions[name] = value
    with pytest.raises(ValueError):
        validate_positions(model, positions)


def test_missing_required_actuator(model, instance):
    positions = dict(instance["initial_configuration"]["actuator_positions"])
    positions.pop("gripper")
    with pytest.raises(ValueError):
        validate_positions(model, positions)


@pytest.mark.parametrize("adapter,scheme", [("mock", "joint_velocity"), ("isaac_sim", "joint_velocity"), ("vendor", "joint_position")])
def test_unsupported_interfaces_rejected(model, adapter, scheme):
    with pytest.raises(ValueError):
        resolve_adapter(model, adapter, scheme)


@pytest.mark.parametrize("reference", ["missing.yaml", "../../../../README.md"])
def test_missing_and_escaping_references(tmp_path, reference):
    folder = tmp_path / "model"
    shutil.copytree(MODEL_ROOT / "demo_arm", folder)
    path = folder / "robot.yaml"
    data = yaml.safe_load(path.read_text())
    data["actuators"] = reference
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        load_model(folder)


def test_instance_model_version(model, instance, tmp_path):
    instance["robot_model"]["version"] = "99.0.0"
    path = tmp_path / "instance.yaml"
    path.write_text(yaml.safe_dump(instance))
    with pytest.raises(ValueError, match="version"):
        load_instance(path, model)


def test_kinematic_reference_is_validated(model, tmp_path):
    folder = tmp_path / "model"
    shutil.copytree(MODEL_ROOT / "demo_arm", folder)
    path = folder / "kinematics.yaml"
    data = yaml.safe_load(path.read_text())
    data["joints"][0]["actuator"] = "nonexistent"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="undefined"):
        load_model(folder)


def test_nonfinite_base_pose_rejected(model,instance,tmp_path):
    instance['base_pose']={'x':float('nan'),'y':0.,'z':0.,'yaw':0.}
    path=tmp_path/'instance.yaml'
    path.write_text(yaml.safe_dump(instance))
    with pytest.raises(ValueError,match='finite'):
        load_instance(path,model)
