"""Saved desired configuration is separate from live adapter feedback."""
from shared.models.domain import WorldObject


def object_map(objects: list[WorldObject]):
    return {o.id: o.position.model_copy(deep=True) for o in objects if o.kind == "object"}


def contained(item: WorldObject, region: WorldObject) -> bool:
    return all(abs(getattr(item.position, axis) - getattr(region.position, axis)) + getattr(item.size, axis) / 2
               <= getattr(region.size, axis) / 2 + 1e-7 for axis in ("x", "y", "z"))


def placement_satisfied(item, target, relation='inside'):
    if relation=='inside':return contained(item,target)
    return (target.kind=='obstacle' and
        all(abs(getattr(item.position,a)-getattr(target.position,a))+getattr(item.size,a)/2<=getattr(target.size,a)/2+1e-6 for a in ('x','y')) and
        abs(item.position.z-item.size.z/2-(target.position.z+target.size.z/2))<=.012)
