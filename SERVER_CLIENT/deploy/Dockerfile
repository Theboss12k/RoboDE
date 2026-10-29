FROM node:24-bookworm-slim AS ui
WORKDIR /opt/robot-ide
COPY package.json package-lock.json ./
COPY SERVER_CLIENT/client/package.json SERVER_CLIENT/client/package.json
COPY BUSINESS_APP/package.json BUSINESS_APP/package.json
COPY ELECTRON_APP/package.json ELECTRON_APP/package.json
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY SERVER_CLIENT/client SERVER_CLIENT/client
COPY SERVER_CLIENT/server/examples SERVER_CLIENT/server/examples
COPY SERVER_CLIENT/server/web/static SERVER_CLIENT/server/web/static
COPY BUSINESS_APP BUSINESS_APP
RUN npm run server:build && npm run business:build

FROM node:24-bookworm-slim
WORKDIR /opt/robot-ide
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates && rm -rf /var/lib/apt/lists/*
ENV ROBOT_IDE_PYTHON=/opt/venv/bin/python PYTHONUNBUFFERED=1
COPY SERVER_CLIENT/server SERVER_CLIENT/server
COPY SERVER_CLIENT/server/examples/projects/apple_transfer SERVER_CLIENT/server/projects/apple_transfer
COPY SERVER_CLIENT/server/examples/projects/dual_arm_cell SERVER_CLIENT/server/projects/dual_arm_cell
RUN python3 -m venv /opt/venv && /opt/venv/bin/python -m pip install --no-cache-dir -r SERVER_CLIENT/server/requirements.txt && /opt/venv/bin/python -m pip install --no-cache-dir --no-deps -e SERVER_CLIENT/server
COPY package.json ./
COPY scripts scripts
COPY BUSINESS_APP/server.py BUSINESS_APP/server.py
COPY --from=ui /opt/robot-ide/SERVER_CLIENT/client/dist SERVER_CLIENT/client/dist
COPY --from=ui /opt/robot-ide/BUSINESS_APP/dist BUSINESS_APP/dist
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=5s CMD /opt/venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/login',timeout=3)"
CMD ["node","scripts/dev.mjs","--server","--built"]
