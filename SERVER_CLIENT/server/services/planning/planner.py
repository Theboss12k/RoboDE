import json
import math
import uuid
from pprint import pformat
from shared.models.domain import Check, Frame, Plan, Pose, TaskSpec, TaskStep, WorldObject
from services.ai_orchestrator.providers import Intent
from services.planning.kinematics import forward, inverse
from services.task_engine.graph import topological_order
from services.validation.trajectory import validate_trajectory
from services.world_model.world import object_map
from services.validation.registry import ROOT, read_yaml


def build_plan(project_id: str, prompt: str, intent: Intent, provider: str, model: dict,
               instance: dict, objects: list[WorldObject], initial: dict, fingerprint: str) -> Plan:
    steps: list[TaskStep] = []
    by_id = {o.id: o for o in objects}
    task_id, plan_id = uuid.uuid4().hex[:12], uuid.uuid4().hex[:12]
    template = read_yaml(ROOT / "task_library/manipulation" / f"{intent.template}.yaml")
    checks = [Check(id="model", label="BOT model & instance", status="passed", message="Schema, model version, actuator IDs, units and declared limits are valid.")]

    def add(key, label, operation, target=None, object_id=None):
        implementation = {"move": "robot_system.registry.models.demo_arm.adapters.mock.adapter.MockAdapter.command",
                          "grasp": "services.execution.controller.SimulationController._execute",
                          "release": "services.execution.controller.SimulationController._execute",
                          "verify": "services.execution.controller.SimulationController.verify"}[operation]
        steps.append(TaskStep(id=key, label=label, operation=operation, target=target, object_id=object_id,
                              dependencies=[steps[-1].id] if steps else [], implementation=implementation, robot_id=instance["instance"]["id"]))

    if intent.template == "pick_place":
        item, target = by_id.get(intent.object_id), by_id.get(intent.target_id)
        if not item or item.kind != "object" or not target or target.kind != "region":
            raise ValueError("Task must reference a known object and a target region")
        high = max(item.position.z, target.position.z) + 0.18
        add("approach", "Approach object", "move", item.position.model_copy(update={"z": high}))
        add("descend", "Align gripper", "move", item.position)
        add("grasp", "Grasp apple" if item.id == "apple" else f"Grasp {item.name}", "grasp", object_id=item.id)
        add("lift", "Lift clear", "move", item.position.model_copy(update={"z": high}))
        add("transfer", "Transfer to basket" if target.id == "basket" else f"Transfer to {target.name}", "move", target.position.model_copy(update={"z": high}))
        add("lower", "Lower into target", "move", target.position)
        add("release", "Release object", "release", object_id=item.id)
        add("retreat", "Retreat from target", "move", target.position.model_copy(update={"z": high}))
        add("verify", "Verify placement", "verify", object_id=item.id)
        success = f"{item.id} is fully inside {target.id} and gripper is empty"
        payload_ok = item.mass_kg <= model["capabilities"]["payload_kg"]
        checks.append(Check(id="payload", label="Object & end effector", status="passed" if payload_ok else "failed",
                            message=f"Object mass {item.mass_kg:.3f} kg; demo payload limit {model['capabilities']['payload_kg']:.3f} kg."))
        fits = all(getattr(item.size, a) < getattr(target.size, a) for a in ("x", "y", "z"))
        checks.append(Check(id="target", label="Target region", status="passed" if fits else "failed", message="Object dimensions must fit entirely within the target volume."))
    else:
        add("home", "Move to initial pose", "move")
        add("verify", "Verify joint state", "verify")
        success = "Measured simulated joints match the saved initial configuration within 0.001"

    task = TaskSpec(id=task_id, description=prompt, robot_id=instance["instance"]["id"], template=intent.template,
                    template_version=template["version"], preconditions=template["preconditions"], postconditions=template["postconditions"],
                    required_capabilities=template["required_capabilities"], object_id=intent.object_id, target_id=intent.target_id,
                    success_condition=success, steps=steps, provider=provider)
    compatible = intent.template in model["capabilities"]["operations"] and intent.template in model["adapters"]["mock"]["capabilities"]
    checks.append(Check(id="capabilities", label="Adapter compatibility", status="passed" if compatible else "failed", message="Local preview adapter and model must both support the requested operation."))
    topological_order(steps)
    checks.append(Check(id="graph", label="Task dependencies", status="passed", message=f"{len(steps)} uniquely identified operations; graph is acyclic."))
    current = dict(initial)
    poses = object_map(objects)
    frames = [Frame(time=0, step_id=steps[0].id, positions=current, objects=poses)]
    clock, held = 0.0, None
    try:
        for step in steps:
            target_q = dict(current)
            if step.target:
                target_q = inverse(model, step.target, current.get("gripper",0.08))
            elif step.id == "home":
                target_q = dict(instance["initial_configuration"]["actuator_positions"])
            elif step.operation == "grasp":
                item = by_id[step.object_id]
                if math.dist(tuple(forward(model, current).model_dump().values()), tuple(poses[item.id].model_dump().values())) > 0.012:
                    raise ValueError("Object is not within grasp tolerance")
                target_q["gripper"] = min(0.06, item.size.x * 0.7)
            elif step.operation == "release":
                target_q["gripper"] = 0.08
            duration = 0.35
            for key in current:
                delta = abs(target_q[key] - current[key])
                limit = model["actuators"]["actuators"][key]
                duration = max(duration, 1.95 * delta / limit["velocity"], math.sqrt(6.2 * delta / limit["acceleration"]))
            samples = max(12, math.ceil(duration * 30))
            duration = samples / 30
            for n in range(1, samples + 1):
                t = n / samples
                blend = 10 * t**3 - 15 * t**4 + 6 * t**5
                q = {key: current[key] + (target_q[key] - current[key]) * blend for key in current}
                if held:
                    poses[held] = forward(model, q)
                if n == samples:
                    if step.operation == "grasp":
                        held = step.object_id
                    elif step.operation == "release":
                        held = None
                frames.append(Frame(time=round(clock + n / 30, 6), step_id=step.id, positions=q,
                                    objects={key: pose.model_copy() for key, pose in poses.items()}, held_object=held))
            current, clock = target_q, clock + duration
        checks.append(Check(id="ik", label="Reachability", status="passed", message="All target poses have an analytic IK solution within declared joint limits."))
        validate_trajectory(model, frames, objects)
        checks.extend([
            Check(id="trajectory", label="Trajectory constraints", status="passed", message=f"{len(frames)} samples at 30 Hz checked for joint position, velocity and acceleration limits."),
            Check(id="collision", label="Sampled geometry", status="passed", message="Links and carried object checked against the table and declared box obstacles."),
        ])
    except ValueError as error:
        checks.append(Check(id="motion", label="Motion feasibility", status="failed", message=str(error)))
    checks.append(Check(id="scope", label="Preview limitations", status="warning", message="Kinematic preview: ideal grasp, no contact physics, self-collision or continuous collision certificate. Isaac Sim validation is still required."))
    code = ("# Generated task manifest. Inspectable; never evaluated as arbitrary Python.\n"
            "# Runtime implementation: services/execution/controller.py\n"
            "from services.execution.controller import SimulationController\n\n"
            f"PLAN_ID = {plan_id!r}\nEXPECTED_FINGERPRINT = {fingerprint!r}\n\n"
            f"TASK = {pformat(task.model_dump(mode='json'), width=90, sort_dicts=False)}\n\n"
            "async def run(controller: SimulationController):\n"
            "    # Runtime rechecks the plan revision, validation and exclusive robot lease.\n"
            "    return await controller.execute_registered_plan(PLAN_ID, EXPECTED_FINGERPRINT)\n\n"
            "# Operation trace\n" + "\n".join(f"# {s.id}: {s.operation} -> {s.implementation}" for s in steps) + "\n")
    return Plan(id=plan_id, project_id=project_id, task=task, checks=checks, frames=frames, code=code,
                duration=round(clock, 3), valid=not any(c.status == "failed" for c in checks), fingerprint=fingerprint)
