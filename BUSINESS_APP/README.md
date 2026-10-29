# Business-facing React application

This folder contains the simpler business UI, room capture, voice input and limited gateway. It shares the planner and project data in `SERVER_CLIENT/server` and reuses rendering/types from `SERVER_CLIENT/client`. It does not expose configuration, adapter generation, credentials or live arming through its gateway.

From PROJECT, with the calculation server running:

```sh
npm run business:build
npm run business:start
```

This listens on loopback port 8080. Set `BUSINESS_ACCESS_CODE` for shared access and use a TLS proxy or `npm run business:phone` to enable phone camera/microphone access. `npm run business:dev` runs Vite on 5174; `npm run business:test` uses an isolated project.

See [business app, phone access and NuRec setup](../docs/BUSINESS_APP.md). Private phone/capture data now lives in `SERVER_CLIENT/server/robot_system/runtime`. The internal calculation API remains on the server's loopback interface; the business gateway only proxies the business API and read-only model assets.
