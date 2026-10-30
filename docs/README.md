# Documentation

For setup from source, start with the [main README](../README.md). These guides
cover individual features and deployment choices. Dated reports describe the
checkout and environment tested at that time.

## Setup and deployment

- [Browser server](../SERVER_CLIENT/README.md) — shared access, Docker, HTTPS and backups
- [Electron desktop](../ELECTRON_APP/README.md) — local launcher and Isaac connections
- [Business App](../BUSINESS_APP/README.md) and [room capture / NuRec](BUSINESS_APP.md)
- [Installers](../installers/README.md) — package requirements and build commands
- [Cloud IDE and Business App](CLOUD_APP.md)
- [GCP Isaac setup](GCP_ISAAC.md) and [deployment status](GCP_DEPLOYMENT_STATUS.md)
- [NVIDIA edition](NVIDIA_EDITION.md)
- [Configuration](CONFIGURATION.md)

## Robots, plans and simulation

- [Robot library](ROBOT_LIBRARY.md) and [URDF import](URDF_IMPORT.md)
- [Adapters and ROS bridge](ADAPTERS.md)
- [AI models and adapters](LLM_ADAPTERS.md)
- [Task pipeline](TASK_PIPELINE.md)
- [Local robotics worker, drivers and physical execution](ROBOTICS_V2_LOCAL.md)
- [Isaac Sim](ISAAC_SIM.md), [scene assets](SCENE_ASSETS.md) and [scene recording](SCENE_RECORDING.md)
- [Runnable examples and API clients](../SERVER_CLIENT/server/examples/README.md)

## Design and development

- [Architecture](ARCHITECTURE.md)
- [Specification](SPECIFICATION.md)
- [Roadmap](ROADMAP.md)
- [Project timeline](PROJECT_TIMELINE.md)
- [Contributing](../CONTRIBUTING.md) and [development scripts](../scripts/README.md)

## Validation and release records

### 30 October 2026

- [All-version QA](QA_ALL_VERSIONS_20261030.md)
- [Simple planning workflow](SIMPLE_PLANNING_20261030.md)
- [Local LLM comparison](LLM_MODEL_COMPARISON_20261030.md)

### 29 October 2026

- [Recording release notes](RELEASE_0.4.0_RECORDING.md)
- [Native NVIDIA scene recording](NVIDIA_SCENE_RECORDING_DEMO_20261029.md)
- [UI overhaul](UI_OVERHAUL_20261029.md) and [UI review](UI_REVIEW_20261029.md)
- [UI and recordings](ROBODE_UI_AND_RECORDINGS_20261029.md)
- [URDF validation](URDF_VALIDATION_20261029.md)
- [Ollama functional tests](OLLAMA_FUNCTIONAL_TEST_20261029.md)
- [Nemotron evaluation](NEMOTRON_MODEL_EVALUATION_20261029.md)

### Earlier records

- [28 October release validation](RELEASE_20261028.md)
- [27 October QA](QA_20261027.md) and [cloud validation](CLOUD_VALIDATION_20261027.md)
- [Server validation](SERVER_VALIDATION.md)

Raw retained model-evaluation results are in [`evaluations/`](evaluations/).
Large recordings, screenshots and local run artifacts are excluded from Git;
some historical reports refer to those local files.
