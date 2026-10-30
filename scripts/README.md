# Development scripts

Run commands from the repository root. Prefer the npm entry points in
[`package.json`](../package.json); they supply the expected Python environment
and paths. Python tools can be run as
`node scripts/python.mjs -m scripts.<module> --help` when they expose a CLI.

## Setup and launchers

| Files | Purpose |
| --- | --- |
| `setup.mjs` | Create `.venv`, install the backend and optionally download Electron |
| `dev.mjs` | Launch the shared backend with Vite, Electron or the production gateway |
| `paths.mjs`, `python.mjs` | Resolve workspace paths, load the server `.env` and run Python |
| `server-control.mjs` | Check or stop the hosted server instance |
| `phone_access.py` | Manage temporary HTTPS Business App access |
| `cloud_session.py` | Manage configured cloud sessions |
| `robotics_worker.py` | Build and manage the optional local Linux worker |
| `bootstrap_isaac_vm.sh` | Set up an Isaac worker on a prepared GPU host |

Cloud and phone-access tools operate on configured services. Read
[cloud setup](../docs/CLOUD_APP.md) and [GCP setup](../docs/GCP_ISAAC.md) before
running them. The robotics worker launcher uses local Docker;
[its guide](../docs/ROBOTICS_V2_LOCAL.md) has the commands and requirements.

## Test servers and fixtures

`ide_test_server.py`, `hosted_test_server.py` and `business_test_server.py` create
disposable workspaces for the Playwright configurations. `contract_scene.py`
supplies the simulated scene used by contract checks. Other `*_server.py` tools
support specific evaluations and recordings. These are development fixtures,
not production launchers.

## Diagnostics and recordings

- `evaluate_local_llms.mjs`, `evaluate_local_converters.mjs`,
  `nemotron_benchmark.py` and `ollama_*` run model evaluations. Some call actual
  configured providers; check their endpoints and arguments before running them.
- `validate_scene_recording.py` checks an already connected native Isaac worker.
- `record_*.mjs` and `render_*.py` capture or render demonstrations.
- `verify_installer_ui.mjs` checks an installed application's interface.

These tools have environment-specific requirements. Store generated output under
`artifacts/`, keep tokens and private connection data out of reports, and record
the test environment in any committed validation summary.
