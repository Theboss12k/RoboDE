# Working on RoboDE

The root npm workspace manages the shared IDE, Business App and Electron shell.
Run setup, builds and tests from the repository root. The [README](README.md)
has the initial setup commands.

## Where changes belong

Browser and desktop features share `SERVER_CLIENT/client/` and
`SERVER_CLIENT/server/`. Keep Electron-specific bridges in `ELECTRON_APP/` and
Business App screens in `BUSINESS_APP/`. The Business App calls the shared backend
rather than maintaining its own planner.

Reusable sample data belongs in `SERVER_CLIENT/server/examples/`. Put generated
reports, screenshots, traces and videos in `artifacts/`; that directory is ignored.
Keep dated validation summaries in `docs/` and link them from the
[documentation index](docs/README.md).

## Check a change

```sh
npm test
npm run typecheck
npm run build
npm run business:build
```

For UI changes, install Chromium with `npx playwright install chromium` and run
the relevant suite: `test:e2e`, `server:test`, `business:test` or `electron:test`.
Electron tests also need `npm run setup`. Tests use temporary project data; avoid
pointing test scripts at your working projects or a live robot.

The local/native worker has separate opt-in tests. A passing mock or transport
test is not evidence of real model inference, native Isaac physics or hardware
operation. Record which environment you actually used.

Update [docs/PROJECT_TIMELINE.md](docs/PROJECT_TIMELINE.md) for functional changes,
bug fixes, configuration changes and test-driven behavior changes. Include the
affected applications, checks run and remaining limitations. Preserve older
entries as historical evidence.

## Before committing

Review `git status --short` and `git diff --check`, then inspect the staged diff.
Commit source, tests, public configuration templates and documentation together.
Do not include saved workspaces, provider credentials, access codes, machine
configuration, installed dependencies or generated installer packages. The private
project and runtime directories are listed in `.gitignore`.

Use `.env.example` for configuration placeholders. Avoid putting credentials in
test fixtures or captured provider responses. Publish installer archives as release
assets; [installers/README.md](installers/README.md) describes how to build them.
