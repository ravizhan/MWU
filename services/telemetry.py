"""匿名遥测（Sentry）：唯一直接使用 sentry_sdk 的模块。

DSN 由资源作者在 interface.telemetry.sentry 提供；未配置、源码运行或调试版资源时不初始化。
"""

import os
import random
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import sentry_sdk
from sentry_sdk.integrations.argv import ArgvIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.modules import ModulesIntegration
from sentry_sdk.types import Event, Hint

from models.interface import InterfaceModel, SentryTelemetry
from models.scheduler import TaskOptionValue

type BlockReason = Literal["no_dsn", "dev_build", "debug_resource"]

_DEBUG_VERSIONS = {"", "dev", "DEBUG_VERSION"}
_MAX_VALUE_LEN = 200
_MAX_OPTIONS_PER_TASK = 50
_MAX_SCREENSHOTS = 4
_MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024
_LOG_TAIL_BYTES = 32 * 1024

_config: SentryTelemetry | None = None
_release = ""
_environment = "production"
_app_root = Path()
_debug_dir = Path()
_blocked_reason: BlockReason | None = "no_dsn"
_failure_rate = 1.0
_initialized = False
_lock = threading.Lock()


def configure(interface: InterfaceModel, app_root: Path) -> None:
    global _config, _release, _environment, _app_root, _debug_dir
    global _blocked_reason, _failure_rate
    _app_root = app_root
    _debug_dir = app_root / "debug"
    sentry = interface.telemetry.sentry if interface.telemetry else None
    _config = sentry
    forced = os.environ.get("MWU_TELEMETRY_FORCE") == "1"
    if sentry is None or not sentry.dsn.strip():
        _blocked_reason = "no_dsn"
    elif "__compiled__" not in globals() and not forced:
        _blocked_reason = "dev_build"
    elif (interface.version or "") in _DEBUG_VERSIONS and not forced:
        _blocked_reason = "debug_resource"
    else:
        _blocked_reason = None

    version_file = app_root / "version"
    client_version = (
        version_file.read_text(encoding="utf-8").strip()
        if version_file.is_file()
        else ""
    ) or "dev"
    release = f"MWU@{client_version}+{interface.name}@{interface.version or 'unknown'}"
    _release = re.sub(r"[/\\\n\t]", "_", release)[:200]
    _environment = (sentry.environment if sentry else None) or "production"
    rate = sentry.failure_attachments_sample_rate if sentry else None
    _failure_rate = 1.0 if rate is None else rate


def apply_consent(enabled: bool) -> None:
    global _initialized
    with _lock:
        if enabled and _blocked_reason is None and not _initialized:
            _init()
            _initialized = True
        elif not enabled and _initialized:
            sentry_sdk.end_session()
            sentry_sdk.get_client().close(timeout=2.0)
            _initialized = False


def status() -> dict[str, Any]:
    return {
        "available": _blocked_reason is None,
        "blocked_reason": _blocked_reason,
        "enabled": _initialized,
    }


def shutdown() -> None:
    apply_consent(False)


def capture_exception(exc: BaseException, *, stage: str) -> None:
    if not _active():
        return
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("failure.stage", stage)
        sentry_sdk.capture_exception(exc)


def start_run(origin: str) -> "RunTrace | None":
    if not _active():
        return None
    return RunTrace(origin)


def _active() -> bool:
    return sentry_sdk.get_client().is_active()


def _init() -> None:
    assert _config is not None
    sentry_sdk.init(
        dsn=_config.dsn,
        release=_release,
        environment=_environment,
        server_name="mwu",
        data_collection={
            "user_info": False,
            "cookies": {"mode": "off"},
            "http_headers": {"request": {"mode": "off"}},
            "http_bodies": [],
            "url_query_params": {"mode": "off"},
            "stack_frame_variables": False,
            "frame_context_lines": 0,
        },
        max_request_body_size="never",
        auto_session_tracking=False,
        traces_sampler=_traces_sampler,
        # 日志只作为 breadcrumb；运行失败由 RunTrace 统一上报，避免重复事件
        integrations=[LoggingIntegration(event_level=None)],
        disabled_integrations=[ArgvIntegration, ModulesIntegration, AsyncioIntegration],
        before_send=_before_send,
        before_send_transaction=_before_send,
        shutdown_timeout=2,
    )
    sentry_sdk.set_user({"id": _install_id()})
    sentry_sdk.start_session(session_mode="application")


def _traces_sampler(ctx: dict[str, Any]) -> float:
    assert _config is not None
    if _config.tracing is False:
        return 0.0
    if ctx["transaction_context"].get("op") == "http.server":
        return 0.0
    rate = _config.traces_sample_rate
    return 1.0 if rate is None else rate


def _install_id() -> str:
    path = _app_root / "config" / "telemetry_id"
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{32}", existing):
            return existing
    new_id = uuid.uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(new_id, encoding="utf-8")
    os.replace(tmp, path)
    return new_id


def _path_pattern(path: Path) -> str:
    forms = {str(path), path.as_posix()}
    return "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))


def _scrub_text(text: str) -> str:
    text = re.sub(_path_pattern(_app_root), "<app>", text, flags=re.IGNORECASE)
    return re.sub(_path_pattern(Path.home()), "<home>", text, flags=re.IGNORECASE)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _before_send(event: Event, _hint: Hint) -> Event:
    scrubbed: Event = _scrub(event)
    scrubbed.pop("server_name", None)
    scrubbed.get("contexts", {}).get("device", {}).pop("name", None)
    return scrubbed


def summarize_options(
    values: dict[str, TaskOptionValue],
    interface: InterfaceModel,
) -> dict[str, Any]:
    """生成任务选项的脱敏摘要：密码字段丢弃，普通文本只记录是否填写。"""
    definitions = interface.option or {}
    summary: dict[str, Any] = {}
    for name, value in values.items():
        if len(summary) >= _MAX_OPTIONS_PER_TASK:
            break
        option = definitions.get(name)
        if name.startswith("_") or option is None:
            continue
        if option.type == "checkbox" and isinstance(value, list):
            summary[name] = ",".join(sorted(value))[:_MAX_VALUE_LEN]
        elif option.type == "hotkey" and isinstance(value, dict):
            summary[name] = {k: v[:_MAX_VALUE_LEN] for k, v in value.items()}
        elif option.type == "input" and isinstance(value, dict):
            fields: dict[str, str] = {}
            for case in option.inputs or []:
                if case.password or case.name not in value:
                    continue
                raw = value[case.name]
                if case.pipeline_type in ("int", "bool"):
                    fields[case.name] = raw[:_MAX_VALUE_LEN]
                else:
                    fields[case.name] = "filled" if raw else "empty"
            summary[name] = fields
        elif isinstance(value, str):
            summary[name] = value[:_MAX_VALUE_LEN]
    return summary


def _span_status(ok: bool | None) -> str:
    if ok is None:
        return "cancelled"
    return "ok" if ok else "internal_error"


class RunTrace:
    """一次整批运行的记录；跨协程与任务线程收集时间戳，finish() 时一次性构建 transaction。"""

    def __init__(self, origin: str):
        self._started = time.time()
        self._origin = origin
        self._lock = threading.Lock()
        self._task_spans: list[dict[str, Any]] = []
        self._failed_task: str | None = None
        self._context: dict[str, str | None] = {}

    def set_context(
        self,
        *,
        controller_type: str | None,
        controller_name: str | None,
        resource: str,
    ) -> None:
        self._context = {
            "controller.type": controller_type,
            "controller.name": controller_name,
            "resource": resource,
        }

    def task_started(self, task_name: str, option_summary: dict[str, Any]) -> None:
        with self._lock:
            self._task_spans.append(
                {
                    "name": task_name,
                    "start": time.time(),
                    "end": None,
                    "ok": None,
                    "options": option_summary,
                }
            )

    def task_finished(self, task_name: str, succeeded: bool) -> None:
        with self._lock:
            record = self._task_spans[-1]
            record["end"] = time.time()
            record["ok"] = succeeded
            if not succeeded and self._failed_task is None:
                self._failed_task = task_name

    def finish(self, status: str, error: str | None, *, stage: str | None) -> None:
        if not _active():
            return
        with self._lock:
            records = list(self._task_spans)
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("run.origin", self._origin)
            scope.set_tag("run.status", status)
            for key, value in self._context.items():
                scope.set_tag(key, value)

            tx = sentry_sdk.start_transaction(
                name="mwu.run", op="mwu.run", start_timestamp=self._started
            )
            tx.set_data("task_count", len(records))
            for record in records:
                span = tx.start_child(
                    op="mwu.task",
                    description=record["name"],
                    start_timestamp=record["start"],
                )
                span.set_data("options", record["options"])
                span.set_status(_span_status(record["ok"]))
                span.finish(end_timestamp=record["end"] or time.time())
            tx.set_status(
                {"success": "ok", "stopped": "cancelled"}.get(status, "internal_error")
            )
            tx.finish()

            if status != "failed":
                return
            failure_stage = stage or "task"
            scope.set_tag("failure.stage", failure_stage)
            scope.fingerprint = [
                "mwu.run.failed",
                failure_stage,
                self._failed_task or "-",
            ]
            if failure_stage == "task" and random.random() < _failure_rate:
                self._attach_failure_files(scope)
            sentry_sdk.capture_message(
                f"Run failed: {error or 'unknown'}"[:500], level="error"
            )

    def _attach_failure_files(self, scope: sentry_sdk.Scope) -> None:
        on_error = _debug_dir / "on_error"
        if on_error.is_dir():
            shots = [
                p
                for p in on_error.iterdir()
                if p.suffix.lower() in (".png", ".jpg")
                and p.stat().st_mtime >= self._started
                and p.stat().st_size <= _MAX_SCREENSHOT_BYTES
            ]
            shots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for shot in shots[:_MAX_SCREENSHOTS]:
                scope.add_attachment(bytes=shot.read_bytes(), filename=shot.name)
        log_file = _debug_dir / "maafw.log"
        if log_file.is_file():
            with log_file.open("rb") as f:
                f.seek(max(0, log_file.stat().st_size - _LOG_TAIL_BYTES))
                tail = f.read().decode("utf-8", "replace")
            scope.add_attachment(
                bytes=_scrub_text(tail).encode("utf-8"), filename="maafw.log"
            )
