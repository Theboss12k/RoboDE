# Implementation status — 0.3

| Area | Implemented | Remaining acceptance / limitations |
| --- | --- | --- |
| Workspace structure | Separate Robots, Environment and Plans; expandable Project → Plans → atomic Tasks; explicit per-task robot assignments | Additional robot families and geometry import |
| Plans and history | Editable named/versioned definitions, immutable compile revisions, CRUD/archive, legacy backup/migration, exact-revision run history and stale rejection | Signed/distributable desktop packaging |
| Multi-robot simulation | Shared-resource serialization, independent parallel tasks, sampled cell checks, per-task outcome evidence and confirmed stop | Continuous collision planning, dynamic handoffs and broader task vocabulary |
| Adapter generation | Virtual/ROS templates, optional AI SDK drafts, joint mappings/units, source review, isolated process transport tests, generated controls and instance connection profiles | SDK drafts remain test-only until a specific vendor transport is implemented and validated |
| Manual controls | Joint setpoints, increments, gripper, source-labeled preview/feedback; isolated tests and connected simulator controls; armed bounded ROS manual controls, resource ownership and expiry | Real ROS controller/hardware acceptance has not been performed |
| Isaac Sim | Authenticated worker/client, native bridge, USD builder, measured observations, explicit reset and watchdog | Native GPU physics/contact tuning remains unverified on this Mac |
| Examples | Nine standardized plan examples; shared YAML/LLM task contract; isolated CLI runner, API and adapter-test clients; two-tool model bundle | Native GPU and physical transport acceptance remain separate |
| Tutorial | Always-available guide for all workspaces, task editing, six generation stages, controls and history; transitions, jumps, keyboard/focus and reduced motion | Update guide with future controls |

Automatic plans remain simulation-only. Passing mock transport or USD parser tests does not establish native physics or real hardware correctness.

See [adapter and ROS setup](ADAPTERS.md), [GPU setup](ISAAC_SIM.md), and [the original specification](SPECIFICATION.md).
