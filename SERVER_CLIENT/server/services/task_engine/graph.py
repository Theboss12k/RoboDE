"""Stable dependency ordering and explicit lifecycle transitions."""
from shared.models.domain import Lifecycle, TaskStep


def topological_order(steps: list[TaskStep]) -> list[TaskStep]:
    by_id = {step.id: step for step in steps}
    if len(by_id) != len(steps):
        raise ValueError("Duplicate task IDs")
    if any(dep not in by_id for step in steps for dep in step.dependencies):
        raise ValueError("Task dependency references an unknown task")
    ordered, visiting, done = [], set(), set()

    def visit(key):
        if key in visiting:
            raise ValueError("Task graph contains a cycle")
        if key in done:
            return
        visiting.add(key)
        for dependency in by_id[key].dependencies:
            visit(dependency)
        visiting.remove(key)
        done.add(key)
        ordered.append(by_id[key])

    for key in by_id:
        visit(key)
    return ordered


TRANSITIONS = {
    Lifecycle.DRAFT: {Lifecycle.VALIDATING},
    Lifecycle.VALIDATING: {Lifecycle.PLANNING, Lifecycle.FAILED},
    Lifecycle.PLANNING: {Lifecycle.PLAN_READY, Lifecycle.FAILED},
    Lifecycle.PLAN_READY: {Lifecycle.SIMULATING},
    Lifecycle.SIMULATING: {Lifecycle.VERIFYING, Lifecycle.CANCELLED, Lifecycle.FAILED, Lifecycle.TIMED_OUT},
    Lifecycle.VERIFYING: {Lifecycle.SIMULATION_PASSED, Lifecycle.FAILED, Lifecycle.CANCELLED},
    Lifecycle.SIMULATION_PASSED: set(),  # Hardware approval is a different controller/policy.
}


def can_transition(current: Lifecycle, target: Lifecycle) -> bool:
    return target in TRANSITIONS.get(current, set())
