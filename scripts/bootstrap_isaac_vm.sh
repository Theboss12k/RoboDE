#!/usr/bin/env bash
# Run as root on the dedicated Ubuntu 24.04 GPU VM. The upload archive contains
# server code only; project data, local credentials and SDK drafts are excluded.
set -euo pipefail
umask 022
bundle=${1:?server archive required}
worker_env=${2:?private worker environment required}
install -d -m 0755 /var/lib/robot-ide/bootstrap
status=/var/lib/robot-ide/bootstrap/status.json
stage() { printf '{"stage":"%s","updated_at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$status"; }
trap 'stage failed' ERR
stage system_packages
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y python3.12-venv ca-certificates curl libglu1-mesa libgl1 libegl1 \
  libglib2.0-0t64 libsm6 libxext6 libxrender1 libxi6 libxrandr2 libxinerama1 \
  libxcursor1 libxt6 libgomp1 libvulkan1 vulkan-tools
id robotworker >/dev/null 2>&1 || useradd --system --home-dir /var/lib/robot-ide --shell /usr/sbin/nologin robotworker
chown robotworker:robotworker /var/lib/robot-ide
chmod 0750 /var/lib/robot-ide
for gpu_group in video render; do
  if getent group "$gpu_group" >/dev/null; then usermod -a -G "$gpu_group" robotworker; fi
done
install -d -o robotworker -g robotworker -m 0750 /var/lib/robot-ide/cache
install -d -o robotworker -g robotworker -m 0700 /var/lib/robot-ide/xdg-runtime
install -d -o robotworker -g robotworker -m 0700 /var/lib/robot-ide/runtime
install -d -o robotworker -g robotworker -m 0770 /var/lib/robot-ide/activity
install -d -o root -g root -m 0755 /opt/Robot_IDE/SERVER_CLIENT/server
tar -xzf "$bundle" -C /opt/Robot_IDE/SERVER_CLIENT/server
chown -R root:root /opt/Robot_IDE
chmod -R go-w /opt/Robot_IDE
ln -sfn /var/lib/robot-ide/runtime /opt/Robot_IDE/SERVER_CLIENT/server/robot_system/runtime
stage isaac_environment
test -x /opt/isaacsim/bin/python || python3.12 -m venv /opt/isaacsim
/opt/isaacsim/bin/python -m pip install --upgrade pip
stage pytorch
/opt/isaacsim/bin/python -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
stage isaac_packages
/opt/isaacsim/bin/python -m pip install 'isaacsim[all,extscache]==6.2.0.0' --extra-index-url https://pypi.nvidia.com
stage worker_dependencies
/opt/isaacsim/bin/python -m pip install -r /opt/Robot_IDE/SERVER_CLIENT/server/requirements-worker.txt
stage watchdog_environment
test -x /opt/Robot_IDE/guard-env/bin/python || python3.12 -m venv /opt/Robot_IDE/guard-env
/opt/Robot_IDE/guard-env/bin/python -m pip install pydantic==2.14.1 PyYAML==6.0.3 jsonschema==4.26.0
install -d -o root -g robotworker -m 0750 /etc/robot-ide
install -o root -g robotworker -m 0640 "$worker_env" /etc/robot-ide/workers.env
cat > /etc/systemd/system/robot-ide-idle-guard.service <<'UNIT'
[Unit]
Description=Stop Robot IDE GPU VM after ten minutes without GPU work
After=network.target
[Service]
Type=exec
User=root
WorkingDirectory=/opt/Robot_IDE/SERVER_CLIENT/server
ExecStart=/opt/Robot_IDE/guard-env/bin/python -m integrations.gcp.idle_guard --idle-seconds 600
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/robot-ide-isaac.service <<'UNIT'
[Unit]
Description=Robot IDE native Isaac Sim worker
After=network-online.target robot-ide-idle-guard.service
Wants=network-online.target
Requires=robot-ide-idle-guard.service
[Service]
Type=exec
User=robotworker
Group=robotworker
WorkingDirectory=/opt/Robot_IDE/SERVER_CLIENT/server
EnvironmentFile=/etc/robot-ide/workers.env
Environment=HOME=/var/lib/robot-ide
Environment=XDG_CACHE_HOME=/var/lib/robot-ide/cache
Environment=XDG_RUNTIME_DIR=/var/lib/robot-ide/xdg-runtime
Environment=ROBOT_IDE_KIT_ROOT=/var/lib/robot-ide/kit
ExecStart=/opt/isaacsim/bin/python -m simulation.isaac_sim.serve --project-scene --host 127.0.0.1 --port 9100
Restart=on-failure
RestartSec=15
KillMode=control-group
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
# First startup and GPU validation are controlled by the deployment operator.
# Enable the idle timer only after installation/shader warm-up has completed.
stage installed
