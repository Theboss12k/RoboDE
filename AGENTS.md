# RoboDE repository instructions

## Change documentation

The user requires a maintained change document. Update `docs/PROJECT_TIMELINE.md`
for every functional change, bug fix, configuration change or test-driven behavior
change made in this repository. Use dated entries, identify affected applications,
describe the resulting behavior, and link detailed evaluation reports when present.
Update an in-progress entry while working; record completed checks and limitations
before delivering. Preserve historical entries instead of rewriting past results.

Never record credentials, private access codes, internal prompts or user data.
Distinguish real model inference from fixture tests, and simulated robot execution
from native Isaac GPU validation or physical hardware tests. Do not claim unrun tests.

## LLM architecture

LLM connections are global, modular adapters implementing
`async def invoke(input: str, system_prompt: str) -> str`. Provider integrations
must remain independent of the application edition, simulator and robot adapters.
Planner and Converter can select different saved LLM profiles.
