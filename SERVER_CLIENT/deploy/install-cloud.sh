#!/bin/bash
# Install the cloud web stack alongside an existing, guarded native Isaac worker.
set -euo pipefail
code_bundle=${1:?code bundle};data_bundle=${2:?initial workspace bundle};access_env=${3:?private access environment};cloudflared_binary=${4:?verified cloudflared binary}
base=/opt/robot-ide-cloud
data=/var/lib/robot-ide-cloud
install -d -o root -g root -m0755 "$base"
install -d -o robotworker -g robotworker -m0700 "$data"
tar -xzf "$code_bundle" -C "$base"
if [ ! -d "$data/projects" ]; then tar -xzf "$data_bundle" -C "$data"; fi
chown -R robotworker:robotworker "$data"
chmod -R go-rwx "$data"
chown -R root:root "$base"
chmod -R go-w "$base"
ln -sfn "$data/projects" "$base/SERVER_CLIENT/server/projects"
ln -sfn "$data/runtime" "$base/SERVER_CLIENT/server/robot_system/runtime"
python3.12 -m venv /opt/robot-ide-cloud-env
/opt/robot-ide-cloud-env/bin/pip install -q -r "$base/SERVER_CLIENT/server/requirements.txt"
install -o root -g robotworker -m0640 "$access_env" /etc/robot-ide/cloud.env
# Preserve the worker secret already installed on the original VM.
cat /etc/robot-ide/workers.env >> /etc/robot-ide/cloud.env
cat >> /etc/robot-ide/cloud.env <<ENV
ROBOT_IDE_DEPLOYMENT=cloud
ROBOT_IDE_ACTIVITY_DIR=/var/lib/robot-ide/activity
PYTHONPATH=$base/SERVER_CLIENT/server:$base
ENV
/opt/robot-ide-cloud-env/bin/python - <<'PY'
from pathlib import Path
import json
values=dict(line.split('=',1) for line in Path('/etc/robot-ide/cloud.env').read_text().splitlines() if '=' in line)
p=Path('/var/lib/robot-ide-cloud/runtime/connections/isaac.json');p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps({'deployment':'remote','url':'http://127.0.0.1:9100','token':values['ISAAC_WORKER_TOKEN'],'load_scene':True,'on_demand':False}))
p.chmod(0o600)
PY
chown -R robotworker:robotworker "$data/runtime"
for mode in api ide business; do
cat > "/etc/systemd/system/robot-ide-cloud-$mode.service" <<UNIT
[Unit]
Description=Robot IDE cloud $mode
After=network-online.target robot-ide-idle-guard.service
Wants=network-online.target
Requires=robot-ide-idle-guard.service
[Service]
Type=exec
User=robotworker
Group=robotworker
WorkingDirectory=$base
Environment=HOME=/var/lib/robot-ide
EnvironmentFile=/etc/robot-ide/cloud.env
ExecStart=/opt/robot-ide-cloud-env/bin/python -m web.cloud $mode
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=control-group
[Install]
WantedBy=multi-user.target
UNIT
done
install -o root -g root -m0755 "$cloudflared_binary" /usr/local/bin/cloudflared
for mode in ide business; do
 if [ "$mode" = ide ]; then port=8083; else port=8084; fi
cat > "/etc/systemd/system/robot-ide-cloud-tunnel-$mode.service" <<UNIT
[Unit]
Description=Robot IDE protected HTTPS session $mode
After=network-online.target robot-ide-cloud-$mode.service
Requires=robot-ide-cloud-$mode.service
[Service]
User=robotworker
Group=robotworker
ExecStartPre=/usr/bin/truncate -s 0 $data/$mode-tunnel.log
ExecStart=/usr/local/bin/cloudflared tunnel --url http://127.0.0.1:$port --no-autoupdate --protocol http2 --logfile $data/$mode-tunnel.log
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
done
cat > /etc/systemd/system/robot-ide-cloud-links.service <<UNIT
[Unit]
Description=Discover the current protected cloud session links
After=robot-ide-cloud-tunnel-ide.service robot-ide-cloud-tunnel-business.service
[Service]
User=robotworker
Group=robotworker
WorkingDirectory=$base
EnvironmentFile=/etc/robot-ide/cloud.env
ExecStart=/opt/robot-ide-cloud-env/bin/python -m integrations.gcp.cloud_apps
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
worker=/opt/Robot_IDE/SERVER_CLIENT/server
cp "$worker/simulation/isaac_sim/worker.py" "$worker/simulation/isaac_sim/worker.py.before-cloud"
for relative in shared/models/instance.schema.yaml simulation/isaac_sim/worker.py simulation/isaac_sim/build_demo_scene.py simulation/isaac_sim/project_scene.py simulation/isaac_sim/scene_assets.py simulation/isaac_sim/native.py integrations/gcp/cloud_apps.py services/validation/registry.py services/api/storage.py services/execution/controller.py; do
 install -o root -g root -m0644 "$base/SERVER_CLIENT/server/$relative" "$worker/$relative"
done
if ! /usr/bin/grep -q '^ROBOT_IDE_CLOUD_APPS=' /etc/robot-ide/workers.env; then
cat >> /etc/robot-ide/workers.env <<ENV
ROBOT_IDE_CLOUD_APPS=1
ROBOT_IDE_CLOUD_LINKS=$data/links.json
ENV
fi
systemctl daemon-reload
systemctl enable robot-ide-cloud-api robot-ide-cloud-ide robot-ide-cloud-business robot-ide-cloud-tunnel-ide robot-ide-cloud-tunnel-business robot-ide-cloud-links
# Restart on updates too: enable --now leaves already-running Python code loaded.
systemctl restart robot-ide-isaac robot-ide-cloud-api robot-ide-cloud-ide robot-ide-cloud-business robot-ide-cloud-tunnel-ide robot-ide-cloud-tunnel-business robot-ide-cloud-links
systemctl is-active robot-ide-cloud-api robot-ide-cloud-ide robot-ide-cloud-business robot-ide-idle-guard robot-ide-isaac
# The caller's temporary archive includes secrets. Remove only the supplied install files.
rm -f -- "$code_bundle" "$data_bundle" "$access_env" "$cloudflared_binary"
