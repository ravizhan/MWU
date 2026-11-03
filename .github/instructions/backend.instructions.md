---
description: "Use when editing MWU backend Python code, including FastAPI routes, worker services, interface loading, scheduler, and update services. Covers API compatibility, runtime safety, and backend validation."
name: "MWU Backend Guidelines"
applyTo: "main.py,backend/**/*.py"
---

# MWU Backend Instructions

## Scope
- Applies to backend Python runtime and API surfaces.
- Keep workspace-wide defaults from `.github/copilot-instructions.md` as baseline.

## API Compatibility
- Keep existing API response envelopes compatible with frontend expectations (`status` plus related payload/message fields).
- Do not rename existing routes, request fields, or response keys unless the task explicitly requires coordinated frontend changes.
- Preserve interface loading and scan-select flow: startup `load_interface_model(...)` in `backend/runtime.py` plus `/api/interface/scan-select/rescan` incremental refresh.

## Runtime Safety
- Avoid blocking FastAPI event loop; wrap blocking device or IO calls with `asyncio.to_thread(...)` (or equivalent pattern) when used from async routes.
- Keep interface mutations protected by `interface_lock`.
- Maintain the device/resource lock recovery chain in `/api/device/state` with liveness checks and reset behavior.

## Agent Integration
- Keep custom registration decorators in exact plain-text form for dynamic parser compatibility:
  - `@AgentServer.custom_action("...")`
  - `@AgentServer.custom_recognition("...")`
- If touching PI environment initialization, keep root `version` file read behavior compatible with `backend/maa_worker/agent_service.py`.

## Dependencies And Validation
- Manage Python dependencies using `uv`; keep `pyproject.toml` and `uv.lock` synchronized.
- For backend-only changes, run targeted validation:
  - `uv sync` (when dependencies change)
  - `uv run main.py` (smoke validation)

## References
- Project architecture and development workflow: `README.md`
- Release build details: `.github/workflows/build.yml`
- Workspace-wide defaults: `.github/copilot-instructions.md`