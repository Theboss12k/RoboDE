# RoboDE for NVIDIA

A build of RoboDE with NVIDIA green accents. By default it uses NVIDIA Isaac Sim on a Nebius GPU VM and NVIDIA Nemotron through Nebius Token Factory. It still supports the built-in simulator, Isaac on this computer, a Google Cloud VM and any other AI model.

## Start it

```sh
npm run dev:nvidia            # browser IDE, development
npm run server:start:nvidia   # shared browser server, built client (run npm run server:build first)
npm run start:nvidia          # desktop app, built client
```

The first launch opens **Set up RoboDE for NVIDIA**:

1. **Simulator.** NVIDIA Isaac Sim (default) or the built-in simulator. New projects use this choice. Existing projects keep their simulator; switch one in its Environment workspace.
2. **Compute.** Nebius GPU VM (default), Google Cloud GPU VM, this machine, or another Isaac worker.
3. **AI model.** Nemotron on Nebius Token Factory (default), Ollama on the RoboDE server, the AI models you already have, or set up later.
4. **Review and save.**

To change these later, use **Runtime & integrations → Run setup again**, or edit the individual settings in Configuration and the Isaac Sim setup panel.

## What is shared and what is separate

- **Shared with the standard build:** projects, robots, control adapters and AI models. A model saved during setup becomes the workspace default for both builds.
- **Separate per build:** the Isaac connection (`robot_system/runtime/connections/isaac.nvidia.json`) and the setup record (`robot_system/runtime/setup/nvidia.json`). Choosing Nebius here never changes the standard build's GCP or local Isaac connection.
- **Never written to setup or Isaac files:** API keys and worker tokens. API keys are stored only in the owner-only AI model secrets file; worker tokens only in the owner-only connection file.

## Nebius GPU VM (connect-only)

RoboDE does not create, start or stop Nebius VMs and never changes Nebius billing.

1. In the Nebius AI Cloud console, create a VM with an NVIDIA RTX-class GPU, such as L40S. A100 and H100 lack the RT cores Isaac Sim requires.
2. Install Isaac Sim and the RoboDE worker. `scripts/bootstrap_isaac_vm.sh` was written for the GCP VM; check its paths before using it on Nebius. Install the guest idle watchdog so the VM powers itself off when unused.
3. Set the worker token from setup as `ISAAC_WORKER_TOKEN` on the VM.
4. Start the VM in the Nebius console. In RoboDE, open **Isaac Sim setup → Nebius GPU VM** and click **Connect to Nebius VM**. RoboDE opens `ssh -N -L 9100:127.0.0.1:9100 user@host` with your key and checks that the worker answers as Isaac Sim.

Using Isaac in a project opens the tunnel automatically. Disconnecting leaves the VM running; stop it in the Nebius console, or let the idle watchdog stop it.

## Nemotron on Nebius Token Factory

Token Factory is hosted inference; no VM is needed. Create a key in Token Factory under **API keys** in your project. During setup, paste the key, click **Check key & find Nemotron models**, and pick a model. It is saved as an AI model named "Nebius Token Factory · ‹model›" and set as the default.

## Status

The setup flow, separate settings, SSH tunnel command and Token Factory profile creation have automated tests. A live connection to a Nebius VM and live Token Factory inference have not been tested from this repository.
