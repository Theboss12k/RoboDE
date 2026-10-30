"""Conservative sampled checks, not a continuous collision/safety certificate."""
import math
from shared.models.domain import Frame, WorldObject
from services.planning.kinematics import link_points, supports_model, link_segments
from services.validation.registry import validate_positions


def inside_box(point, obstacle: WorldObject, padding: float = 0.025) -> bool:
    return all(abs(value - getattr(obstacle.position, axis)) <= getattr(obstacle.size, axis) / 2 + padding
               for value, axis in zip(point, ("x", "y", "z")))


def validate_trajectory(model: dict, frames: list[Frame], objects: list[WorldObject], check_geometry: bool = True) -> None:
    if len(frames) < 2:
        raise ValueError("Trajectory needs at least two samples")
    obstacles = [o for o in objects if o.kind == "obstacle"]
    previous_velocity = None
    for index, frame in enumerate(frames):
        validate_positions(model, frame.positions)
        points = link_points(model, frame.positions) if check_geometry and supports_model(model) else []
        floor_points = points[1:]
        if model['kinematics']['solver']=='serial_chain_dls_v1' and points:
            # Coincident fixed/root joint frames represent the anchored base, not an arm segment.
            floor_points = [p for p in floor_points if math.dist(p, points[0]) > 1e-9]
        if any(p[2] < 0.022 for p in floor_points):
            raise ValueError(f"Link intersects table at sample {index}")
        for start, end in (link_segments(model,frame.positions) if points else []):
            length = math.dist(start, end)
            count = max(2, math.ceil(length / 0.015))
            for n in range(count + 1):
                point = tuple(a + (b - a) * n / count for a, b in zip(start, end))
                if any(inside_box(point, o) for o in obstacles):
                    raise ValueError(f"Sampled link collision with obstacle at t={frame.time:.2f}s")
        for object_id, position in frame.objects.items():
            item = next(o for o in objects if o.id == object_id)
            radius = max(item.size.x, item.size.y, item.size.z) / 2
            if position.z < item.size.z / 2 - 1e-6:
                raise ValueError(f"Object {object_id} intersects table at sample {index}")
            # Face contact on a support surface is valid; positive AABB penetration is not.
            if any(all(abs(getattr(position,a)-getattr(o.position,a)) < (getattr(item.size,a)+getattr(o.size,a))/2-1e-6 for a in ('x','y','z')) for o in obstacles):
                raise ValueError(f"Object {object_id} collides with an obstacle")
        if index == 0:
            continue
        dt = frame.time - frames[index - 1].time
        if dt <= 0:
            raise ValueError("Trajectory times must strictly increase")
        velocity = {k: (v - frames[index - 1].positions[k]) / dt for k, v in frame.positions.items()}
        for key, value in velocity.items():
            limit = model["actuators"]["actuators"][key]
            if abs(value) > limit["velocity"] + 1e-5:
                raise ValueError(f"{key}: velocity exceeds declared limit")
            if previous_velocity is not None and abs(value - previous_velocity[key]) / dt > limit["acceleration"] + 0.02:
                raise ValueError(f"{key}: acceleration exceeds declared limit")
        previous_velocity = velocity
