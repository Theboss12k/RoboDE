"""Load trusted BOT data with schema, path containment and semantic checks."""
import math
import json
from pathlib import Path
import yaml
from jsonschema import validate as schema_validate
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ROOT.parents[1]
MODEL_ROOT = ROOT / "robot_system/registry/models"


def validate(data, schema):
    try:
        schema_validate(data, schema)
    except ValidationError as error:
        location = ".".join(str(p) for p in error.absolute_path) or "definition"
        raise ValueError(f"{location}: {error.message}") from error


def read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise ValueError(f"{path.name}: invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected a YAML mapping")
    return data


def component(folder: Path, relative: str) -> Path:
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise ValueError(f"Missing or invalid model reference: {relative}")
    return path


def validate_positions(model: dict, positions: dict, complete: bool = True) -> None:
    actuators = model["actuators"]["actuators"]
    if complete and set(positions) != set(actuators):
        raise ValueError("Configuration must include every actuator exactly once")
    for name, value in positions.items():
        if name not in actuators:
            raise ValueError(f"Unknown actuator: {name}")
        limits = actuators[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name}: position must be finite")
        if name not in model.get('continuous_joints',[]) and not limits["min"] <= value <= limits["max"]:
            raise ValueError(f"{name}: {value:.9g} outside [{limits['min']}, {limits['max']}] {limits['unit']}")


def load_model(folder: Path) -> dict:
    robot = read_yaml(folder / "robot.yaml")
    schema = read_yaml(ROOT / "shared/models/bot.schema.yaml")
    validate(robot, schema)
    model = {"robot": robot}
    schemas = read_yaml(ROOT / "shared/models/components.schema.yaml")
    for key in ("kinematics", "actuators", "capabilities"):
        model[key] = read_yaml(component(folder, robot[key]))
        validate(model[key], schemas[key])
    for key in ("control_schemes", "adapters"):
        model[key] = {name: read_yaml(component(folder, path)) for name, path in robot[key].items()}
        for name, value in model[key].items():
            validate(value, schemas["control_scheme" if key == "control_schemes" else "adapter"])
            if value["id"] != name:
                raise ValueError(f"{key}: declaration ID {name} does not match file ID {value['id']}")
    actuators = model["actuators"]["actuators"]
    if not actuators:
        raise ValueError("Robot must declare actuators")
    for name, actuator in actuators.items():
        if not actuator["min"] < actuator["max"] or actuator["velocity"] <= 0 or actuator["acceleration"] <= 0:
            raise ValueError(f"Invalid actuator limits: {name}")
        if not all(math.isfinite(actuator[k]) for k in ("min", "max", "velocity", "acceleration")):
            raise ValueError(f"Non-finite actuator limits: {name}")
    joint_ids = {j["actuator"] for j in model["kinematics"]["joints"] if j["type"]!="fixed"}
    if not joint_ids.issubset(actuators):
        raise ValueError("Kinematics references undefined actuators")
    links = model["kinematics"]["links"]
    if any(not math.isfinite(value) or value <= 0 for value in links.values()):
        raise ValueError("Kinematic link dimensions must be finite and positive")
    if model['kinematics']['solver']=='serial_chain_dls_v1':
        from services.planning.serial_ik import validate_chain
        validate_chain(model)
    for component_spec in model['capabilities'].get('components',{}).values():
        key=component_spec['actuator']
        if key not in actuators or not all(isinstance(component_spec[v],(float,int)) and not isinstance(component_spec[v],bool) and math.isfinite(component_spec[v]) and actuators[key]['min']<=component_spec[v]<=actuators[key]['max'] for v in ('closed','open')):
            raise ValueError('Component opening endpoints must fit its configured actuator limits')
    for name, adapter in model["adapters"].items():
        if adapter["category"] != ("physical" if adapter["environment"] == "hardware" else "virtual"):
            raise ValueError(f"Adapter {name}: target category does not match environment")
        if not set(adapter["control_schemes"]).issubset(model["control_schemes"]):
            raise ValueError(f"Adapter {name} references an undefined control scheme")
        if not set(adapter["capabilities"]).issubset(model["capabilities"]["operations"]):
            raise ValueError(f"Adapter {name} declares capabilities missing from the model")
    if (folder / 'source/import.json').exists():
        model['source_import'] = json.loads((folder / 'source/import.json').read_text())
        source=(folder/'source/package'/model['source_import']['urdf_path']).resolve()
        if source.is_relative_to((folder/'source/package').resolve()) and source.is_file():
            from services.imports.urdf import parse_urdf
            parsed=parse_urdf(source.read_bytes());model['geometry']=parsed['geometry'];model['urdf_joint_metadata']=parsed['joints']
            meshes={m['uri']:m for m in model['source_import'].get('meshes',[])}
            for item in model['geometry']:
                if item['shape']=='mesh':item['asset']=meshes.get(item['parameters']['uri'])
    return model


def load_instance(path: Path, model: dict) -> dict:
    data = read_yaml(path)
    validate(data, read_yaml(ROOT / "shared/models/instance.schema.yaml"))
    if any(not math.isfinite(v) for v in data.get("base_pose", {}).values()):
        raise ValueError("Robot base pose must contain finite world coordinates and yaw")
    robot = model["robot"]
    if data["robot_model"] != {"id": robot["id"], "version": robot["version"]}:
        raise ValueError("Instance model ID/version does not match registered model")
    initial = data["initial_configuration"]
    units = initial.get("actuator_units", {})
    if initial["position_unit"] == "per_actuator":
        expected = {key: actuator["unit"] for key, actuator in model["actuators"]["actuators"].items()}
        if units != expected:
            raise ValueError("Initial actuator units must match every model actuator (rad for rotation, m for gripper)")
    elif any(a["unit"] != initial["position_unit"] for a in model["actuators"]["actuators"].values()):
        raise ValueError("Mixed rotational and linear actuators require explicit per-actuator units")
    validate_positions(model, initial["actuator_positions"])
    return data


def resolve_adapter(model: dict, name: str, scheme: str) -> dict:
    adapter = model["adapters"].get(name)
    if not adapter or scheme not in adapter["control_schemes"]:
        raise ValueError(f"Adapter {name} does not support control scheme {scheme}")
    if not adapter["available"]:
        raise ValueError(adapter["unavailable_reason"])
    return adapter


def registry() -> list[dict]:
    return [load_model(path.parent) for path in sorted(MODEL_ROOT.glob("*/robot.yaml"))]
