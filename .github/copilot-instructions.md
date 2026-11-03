# MWU Project Guidelines

## Code Style
- Follow existing directory boundaries and naming style; do not move modules across backend, frontend, and updater layers unless required.
- Keep changes scoped to the touched area and preserve existing API contracts between backend and frontend.
- Use repository toolchains only:
  - Python: `uv` (do not switch to pip/poetry for project tasks)
  - Frontend: `pnpm` in `front/`
  - Updater: Go Modules in `updater/`
- Keep lockfiles and generated boundary files in sync when dependencies change (`uv.lock`, `front/pnpm-lock.yaml`, `updater/go.sum`).
- Before using or introducing any third-party library, query that library's latest documentation with Tavily or Context7, read the documentation, and only then modify the related code.

## Architecture
- Backend CLI entry is `main.py` (arguments, single-instance check, `uvicorn.run`); the FastAPI app and lifecycle live in `backend/app.py`, with routes split across `backend/api/` and static hosting for `page/`. Process-level singletons (app root, interface/language loading, `AppState`) are in `backend/runtime.py`.
- Worker orchestration lives in `backend/maa_worker/worker.py`; concrete runtime responsibilities are split in `backend/maa_worker/` services (`agent_service.py`, `device_service.py`, `task_service.py`, `event_service.py`, `pipeline_override.py`).
- Interface and settings schemas live in `backend/models/` and are consumed by both API and runtime.
- Frontend source is in `front/src/`:
  - app bootstrap: `front/src/app/`
  - state management: `front/src/stores/`
  - API client modules: `front/src/services/api/`
- Frontend build output goes to `page/` and is served by backend.

## Build and Test
- Backend setup/run:
  - `uv sync`
  - `uv run main.py`
- Frontend setup/run/build/lint:
  - `cd front && pnpm install --frozen-lockfile`
  - `cd front && pnpm dev`
  - `cd front && pnpm build`
  - `cd front && pnpm lint`
- Updater build:
  - `cd updater && go build`
- There is no single unified test command. Validate only the affected area:
  - Backend changes: run `uv run main.py` for smoke validation
  - Frontend changes: run `cd front && pnpm build && pnpm lint`
  - Updater changes: run `cd updater && go build`

## Conventions
- `interface.json` is loaded once at backend startup (`load_interface_model` in `backend/runtime.py`). There is no general interface hot-reload API.
- The project extends PI option types with `scan_select`; keep both model support and `/api/interface/scan-select/rescan` flow intact when editing interface-related code.
- Agent custom registration parsing is string-pattern based in `backend/maa_worker/agent_loader.py` and expects decorator lines in this exact form:
  - `@AgentServer.custom_action("...")`
  - `@AgentServer.custom_recognition("...")`
  Keep double quotes and plain decorator text to avoid silent registration failures.
- Device/resource lock recovery relies on `/api/device/state` plus backend connection liveness checks; preserve this chain when changing device lock logic.
- Task order persistence must merge new interface tasks that are missing from saved `taskOrder` (see `front/src/stores/task-config/taskConfig.ts`), instead of overwriting with persisted order only.
- Agent environment initialization reads the root `version` file directly in `backend/maa_worker/agent_service.py`; packaged and local runtimes should both ensure this file exists.

## Docs
- Project overview and development details: `README.md`
- Release build source of truth: `.github/workflows/build.yml`
- Commit message convention: `.github/.copilot-commit-message-instructions.md`