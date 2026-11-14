# Repository Guidelines

## Scope

MWU is a generic UI for [MaaFramework](https://github.com/MaaXYZ/MaaFramework), run by one person locally or on a trusted LAN — never a multi-user service. Users supply `resource/`, `interface.json`, and `agent/`; improve the generic loader/runtime, never bake in project-specific behavior.

Write the simplest correct implementation and keep the backend/frontend API contract. No accounts, tenancy, distributed coordination, generic frameworks, compatibility layers, or speculative abstractions. Safeguard only real failure modes (malformed config, unsafe paths, interrupted writes, cancellation, subprocess cleanup, overlapping runs, background threads): validate at the boundary and surface failures instead of re-validating normalized data, suppressing exceptions, falling back silently, or retrying without cause.

## Layout

`main.py` is the CLI (single-instance check, native dispatch, `uvicorn.run`). `backend/`: `runtime.py` (app root, interface/language loading, `AppState`), `app.py` (FastAPI, lifespan, static/SPA), `api/`, `core/` (paths, state, settings IO, secrets), `maa_worker/` (`execution.py` lifecycle, `worker.py` DI, MAA services, sink/focus), `scheduler/`, `services/` (update, telemetry, notification, log export), `models/`. `front/src/`: `app/`, thin `views/`, `components/` (shared in `common/`), Pinia `stores/`, `services/`, `validation/`, `types/`, `utils/`; Vite builds `page/`. Also `.github/workflows/`, `updater/` (Go), `deploy/` (downstream templates; its `install.yml` replaces MaaPracticeBoilerplate's). Package = `page/` + Nuitka backend + MaaAgentBinary + updater.

## Architecture

`APP_ROOT_DIR` (page/config/agent/deps; MAA toolkit and agent cwd) differs from `PROJECT_DIR` (`interface.json`, all PI-relative paths); packaged both are the exe dir, from source the project dir is `assets/`. Uvicorn binds `0.0.0.0:5566`; browser launch and delegation use loopback. `/assets` → `page/assets`, `/resource` → project `resource/`, SPA fallback `page/index.html`. `/api/file` and `/api/file/list` (one level) take project-contained paths only: drop a leading `./`, reject `..`, empty segments, absolute and drive paths, omit escaping symlinks.

`AppState` owns broadcaster/history, settings, device/task/agent/focus state, the single `active_run` slot, update gate, scheduler refs, and shutdown. `MaaWorker` is a DI container: module-level CPU `Resource`, per-runtime `Tasker` and HTTP client, MAA services sharing a back-reference. Lifespan builds both plus history and schedulers, converging native registrations while APScheduler is paused.

Settings and task-config writes encrypt, then `atomic_write_json` (tmp+fsync+replace under `SETTINGS_LOCK`); a failed save keeps the old file. `/api/settings` POST preserves `panel.customDevices`. `password` inputs are AES-128-GCM at rest (key in the per-user data dir) in `settings.json`, `task_config.json`, and APS job kwargs, plaintext in memory and responses. APS jobs and history share `config/scheduler.sqlite`.

### Execution

Manual, in-app scheduled, and native starts all go through `execution.py`. `_complete_run` admits to the single slot, normalizes the payload (≥1 valid task before any command), runs interface `pretask` executables (no timeout; only stop ends them) and `PreTaskCommand` shell commands (configured timeout; failure aborts), prepares device/resource (skipped when reusing a locked connection), runs `TaskService`, records history, and clears the slot.

`_claim_slot` resets `stop_flag` on admission only — later resets lose stops. `run_process()` and `PretaskService` poll it, and cancelling during pre-tasks must drain the shielded pre-task future before clearing `active_run`. `run_process()` emits no terminal events: `_complete_run` emits `task.completed`/`task.failed` after history, and slot clearing plus `publish_task_terminal` share one synchronous segment, so no `task.started` can precede it.

Runs execute inside wakepy `keep.running` (blocks sleep, not screen-off; activation failure logs and is ignored), with enter/exit in the event-loop coroutine. `keep_awake.py` patches wakepy 1.0.0's Windows method so failed activation releases its non-daemon inhibitor thread. `configuration_locked` is set when `set_resource()` succeeds after connect; locked `connect()`/`set_resource()` refuse while the connection lives, and `reset_connection_state()` releases it on connection/liveness/screencap failure or when execution replaces an incompatible connection.

Agents start lazily via one-shot `ensure_started_once()` in `TaskService.start()`; `started_once` ratchets on failure, and already-connected external processes are cleaned up before the aggregate error is kept. Embedded agents use a custom finder, `deps/` precedence, a client-mode `_BlackMagicAgentServer` stub, and regex/AST registration; external ones use `AgentClient` plus subprocesses. The decorator regex matches only `@AgentServer.custom_action("...")`/`custom_recognition("...")` with double quotes and the `class` line directly below; anything else fails silently.

Execution and option maps key on unique `task.name`, not `task.entry` (which may repeat and resolves only at `post_task`). Repeated names share one option map and run in order; the UI uses per-entry `uid`; `active_run.task_name` is display only.

### Interface and options

Fragments may contain only `task`/`option`/`preset`/`pretask`/`import`/`global_option`/`setting`, resolved from the app root. Duplicate tasks/presets and path escapes fail loudly; later option keys override; groups dedupe by name (first wins). Post-merge validation covers references, presets, pre-tasks, settings, and duplicate case/input/hotkey names. `scan_select` expands `scan_dir` + `scan_filter` into in-memory cases, rescanned via `/api/interface/scan-select/rescan` under `interface_lock`.

`PipelineOverrideService` applies task `pipeline_override`, then deep-merges `global_option` → resource → controller → task options, including recursive cases, applicability, input coercion, placeholders, and `scan_select`; hotkeys convert per controller; an omitted `type` serializes as `select`. `interface.setting` only groups UI: its values and PI `pretask.option` values (edited inline in `PreTaskList.vue`) persist in `settings.json.globalOptionValues`, and only `global_option` members enter overrides.

`input_type` `file`/`directory` (requires `pipeline_type` `string`) render a text box plus `ProjectPathPickerDialog.vue` (lazy `/api/file/list`, `.` = project dir) instead of PI's system dialog. Values are project-relative; `InputCase.runtime_value` absolutizes them under `PROJECT_DIR` for overrides and pretask payloads (absolute/empty pass through; existence unchecked).

`settings.json.pretaskEnabled` is keyed by `name` or compact JSON `[exec, ...args]` (byte-identical between `Pretask.key` and frontend `pretaskKey`; duplicates rejected; missing = enabled). It is rewritten when switching or resetting to a preset declaring `pretask` (unlisted → unchecked) or on load when empty, so `App.vue` loads settings before `loadConfig()`. Manual start awaits `flushSaves` and aborts on save failure. `preset.controller` only filters presets in the UI.

`config/task_config.json` holds `selectedPreset` plus per-preset `tasks`/`taskOptions`/`preTasks`; normalization seeds missing presets, drops invalid names keeping order and repeats, normalizes options, and never appends to an existing queue.

`$key` text resolves against `settings.json.ui.language` (mapped to `interface.languages` keys), flat key then dotted path; a miss yields `None`/caller fallback, never a literal `$key`. `resolve_tree` keeps originals for PI env payloads, and `ui.language` is authoritative — the store backfills from the `locale` cache only when it is `null`. Custom devices are validated/canonicalized (strict custom, lenient scanned Adb) into `panel.customDevices`, with scan winning duplicates.

### Events

MAA threads push `RealtimeEvent` into `AppState.message_conn` (`SimpleQueue`, 0.05s throttle); `log_monitor` polls every 100ms, records non-modal events in bounded history, and fans out via `LogBroadcaster` to SSE `/api/logs` — if it dies, SSE goes silent. Adding an event also touches `types/realtimeModel.ts`, listeners in `app/main.ts`, and dispatcher/SSE normalization.

`SinkHandler` → `UnifiedFocusResolver` → `FocusEventProcessor`; `log`/`toast`/`notification`/`dialog` map to `focus.display`, and `notification` may also fire system/external notifications with policy re-read from `settings.json`. Agent EventSink subclasses are AST-detected and registered on MAA objects directly, bypassing focus. `FocusEventProcessor` blocks the sink callback until `POST /api/focus/{id}/confirm` or cancellation; `focus.modal` carries the full pending snapshot, skips history, replays on SSE connect, and has an intentionally empty `message`. `TaskService.stop()` sets `stop_flag` under the focus lock, then releases pending modals — keep that order. It is a confirmation gate, not pause/resume.

`notification.channels` is a `type`-discriminated list. Apprise plugin classes are instantiated directly, never URLs (URL discovery needs a plugin dir absent under Nuitka); DingTalk/Feishu/WeCom and webhook are local `NotifyBase` subclasses because apprise ignores 200-with-error-code bodies and its Feishu lacks signing. `app_id` stays ASCII `MWU`. Sends run on a daemon thread; failures log status code/exception type only (URLs hold tokens) and never raise. `attachScreenshot` grabs a JPEG on the send thread (none when disconnected, ≤10s, failure only logs and never resets the connection) and attaches it in memory: SMTP/Telegram/OneBot natively, WeCom as a follow-up re-encoded image, webhook via `{{screenshot}}` Base64.

Each `notifyOn*` setting gates one point through `EventService.notify(trigger, ...)`, which re-reads settings and always logs; only the push is gated. Points: run start, per-task success/failure (skipped on stop), pre-task failure (not on user stop), connect failure after all retries and on manual `POST /api/device`, scheduled skip on a run conflict (not update-in-progress), and scheduler errors. Whole-run terminal notifications stay in `publish_task_terminal` with pre-read settings, and `DeviceService.connect()` sends none itself so retries don't repeat it.

### Scheduling

`AsyncIOScheduler` + `SQLAlchemyJobStore`; `scheduled_job_fired` must stay module-level in `scheduler/manager.py` (persisted reference), with `_CALLBACK_STATE` bound in `initialize()`. Conflicts `busy_manual`/`busy_scheduled`/`update_in_progress`: manual rejections write no history, scheduled skips do. SQLite work runs via `asyncio.to_thread`, finalization is shielded, pre-start cancellation is compensated, and `scheduler_executions` keeps 1000 rows.

`SystemScheduler` is a stateless desired-set adapter over `schtasks`/`launchctl`/`crontab`/`NullBackend`. Converge re-registers enabled tasks, removes orphans, isolates per-task failures, and reports listing failure as `ConvergeReport.list_error` (backends raise rather than return empty). Create registers native first and unregisters if APS fails; update goes APS then native (raises; startup converge repairs); delete/pause/resume return `False` only for a missing job. Startup registration failures degrade to in-app dispatch, and `--scheduled-task <id>` delegates to a running instance via loopback, else runs with origin `native`.

`PortableCronStr` (wrapping `CronStr`) allows 5 fields, single value or `*`, a concrete minute, and no day+DOW combo; it feeds both APScheduler and OS conversion. `validation/cron.ts` mirrors it and gates the wakeup switch; both share `tests/fixtures/validation_contract.json`. Same-minute native conflicts are blocked on create/update.

### Update, version, telemetry

`check_update()` returns an `UpdatePlan` comparing `interface.version`; MirrorChyan first (its URL when present, `update_type` incremental → `incremental`), else the GitHub release with the same tag; without MirrorChyan, GitHub `latest` (stable) or newest release (beta). Only the newest overlapping check is stored. Assets from `deploy/install.yml`: full `<name>-<os>-<arch>-<tag>.7z`, resource `<name>-resource-<os>.<arch>-<tag>.7z` (the `.` keeps older clients matching `<os>-<arch>` off it), and `mwu-release.json` `{version, mwu_version}`. The resource package is used only when the release's `mwu_version` matches local `mwu-install.json` and no resource file overrides a client file; otherwise full. Proxy applies to non-MirrorChyan sources, SHA-256 is verified when given, and downloads go to fixed `update_package`. `update_in_progress` is set before the first `await`, gates admission, and clears on failure or in the updater-loop `finally`; success shuts the process down.

`mwu-updater -type full|resource|incremental` does guarded extraction, exit-code-10 self-update, webhook shutdown, lock wait, and recovery of a previous `update_backup/` (committed → discard, else restore; failure aborts). `apply.go` validates paths lexically and against symlink/junction components before reading; full copies the package and deletes files dropped from the old manifest (none without one); resource requires matching `mwu_version` and no overrides; incremental follows `changes.json`, and `deleted_dir` only removes dirs left empty. Apply is transactional: `created.json` journal first, manifest last, replaced files in `update_backup/files/`, `committed` marker before cleanup; failure rolls back and restarts the old binary, success restarts detached.

Root `version` is a gitignored, possibly stale artifact; release writes `github.ref_name` to `build/main.dist/version`, and `build_pi_env()` reads it into `PI_CLIENT_VERSION` (empty if missing) while setting `PI_USER_DATA_DIR` to the app root. `services/telemetry.py` is the only `sentry_sdk` importer, enabled only with `interface.telemetry.sentry.dsn`, a Nuitka build (`__compiled__` or `MWU_TELEMETRY_FORCE=1`), a non-debug resource version, and `telemetry.helpImproveSoftware`; init failure logs and disables. One `RunTrace` per run finishes after history and before slot clearing, with redacted option summaries per task span. Failed runs send one event tagged `failure.stage`; task failures attach `on_error` screenshots and the `maafw.log` tail, while `pretask`/`device` failures send only the stage. Focus templates with `trace` add `mwu.node` spans. Logging is breadcrumb-only outside `backend.maa_worker.execution`.

### Frontend

`main.ts` installs Pinia/router/i18n, anchors naive-ui styles, and registers SSE listeners before mount. `App.vue` provides config/message/dialog providers, hosts `FeedbackBridge` (must stay under `NMessageProvider`) and `FocusDialogHost`, hydrates interface/task config/settings, and owns navbar/dock/update UI. `AppMain.vue` uses `<router-view>` `mode="out-in"`; keep each view inside one keyed `<div>`, since multi-root breaks routing. Home is eager, other routes lazy.

API modules use raw `fetch()` with their own mapping/feedback; `services/api/core/types.ts` shares only envelope types. `SSEClient` does a minimal shape check and reopens only after native `EventSource` reports `CLOSED`. Settings serializes whole-document saves through a queue; task-config owns queue/options/presets with debounced saves, trusts server normalization, and never persists after a failed load; `focus/focus.ts` owns the dialog queue, blocking modals first.

`stopActiveAndRestart` stops, waits (bounded) for `TaskRunning` to clear, then retries `busy_manual` every 500ms up to 60s; it never retries other conflicts, shares one in-flight sequence, and is cancelled by `cleanup()`. `TaskSelectList` keeps `:delay="120" :delay-on-touch-only="true"`, and `SchedulerTaskDialog` enables wakeup only for eligible cron.

`/api/logs/export` zips SSE history (`mwu.log`), line-aligned tails of `debug/*.log` and `updater.log`, and the newest `debug/on_error`/`debug/vision` images within a size budget. Plaintext `password` values (including JSON-escaped) are masked, collected from settings, all presets, scheduled jobs, and `AppState.run_secrets` (added before pre-tasks, kept until restart); text logs are snapshotted before collecting passwords.

Screenshot save/copy uses lossless PNG `/api/device/screenshot` at the controller's capture size (the frame tasks see; raw size would change a shared option mid-run). Clipboard copy needs a secure context, so plain-HTTP LAN errors. Tap mode maps `object-contain` preview clicks to pixels (`utils/containedPoint.ts`) and posts `/api/device/click`; a failed click on a dead connection releases the lock.

## Commands

Backend: `uv sync` (Python >=3.13), `uv run main.py` (no `--reload`), `uv run pytest tests/ -q`, `uv run ruff check .` / `uv run ruff format .`.

Frontend (`cd front`, pnpm 11, Node >=24.13.0): `pnpm install --frozen-lockfile`, `pnpm dev` (proxies `/api` to `:5566`), `pnpm build` (to `../page`), `pnpm lint`, `pnpm format`, `pnpm type-check`, `pnpm test:run`.

Updater: `cd updater && go build`. Nuitka deps: `uv sync --locked --group build`; build steps live in `.github/workflows/build.yml` and `README.md`. `uvx pre-commit run --all-files` needs frontend deps; commit hooks format staged files only.

## Coding Style

One cohesive responsibility per file, ideally under ~800 lines; split by responsibility, not line count. Small public APIs, no circular deps, no unrelated refactors. Python 3.13+, snake_case, modern syntax (`list[T]`, `X | None`, `type`), no version checks or shims.

Frontend: 2-space, LF, 100 cols, double quotes, no semicolons; Tailwind v4 with naive-ui. Lint forbids `as`, enums, `else`, `try/catch` (use literal unions, early returns, `utils/tryCatch.ts`), raw `fetch` outside `services/api` and `utils/interface/content.ts`, `useMessage` outside `FeedbackBridge.vue`, and `@/stores` barrel imports inside `stores/`. oxlint (type-aware for `.ts`) owns every rule it implements; `eslint.config.ts` disables those via `eslint-plugin-oxlint`, keeps typed `.vue` rules, and adds Vue/vue-i18n/style rules. Inside `withVueTs()`, scope typed rules with `files`, never `ignores`.

Vue APIs and naive-ui template components are auto-imported; import explicitly only values used outside templates and types. Never hand-edit `front/auto-imports.d.ts` or `front/components.d.ts`. User-facing text goes in mirrored zh-CN/en-US dictionaries. Respect pnpm `catalog:` and lock files, and check current official docs before adding or changing third-party library usage.

## Testing

Backend tests live in `tests/unit/` (fixtures `tests/conftest.py`); Vitest tests are colocated in `front/src/`, with shared MSW/EventSource setup in `front/src/tests/`. CI runs ruff, pytest, Vitest, and type-check; lint/format are local.

Keep tests minimal and behavioral: extend existing ones, add cases only for plausible user-visible bugs or real contract/boundary/state transitions, and delete tests for removed behavior. Never assert source text, exact wording, call wiring, or mock forwarding.

Verify proportionally: backend → focused pytest plus a `uv run main.py` or `import main` smoke; frontend → build/lint/type-check, relevant Vitest, and a headless Chrome smoke (`--headless=new --disable-extensions`); updater → `go build` plus a focused scenario. Doc-only edits need no runs.

## Commits & PRs

Conventional Commits (rules in `.github/.copilot-commit-message-instructions.md`), short subjects, no trailing period. PRs describe the change, list validation, link issues, and include screenshots for visible frontend changes.

## AI Assistant Practices

Use `task` subagents (`scout` for read-only research) for independent slices; the main agent owns decomposition and cross-task contracts. Check project memory/history before substantial changes and verify against current code. Never write intermediate status, investigation reports, or planning docs into the repo unless asked.
