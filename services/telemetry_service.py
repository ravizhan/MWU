"""Opt-in Sentry telemetry for MWU.

MWU installs its client as Sentry's global client, exactly as
``sentry_sdk.init`` does.  Revocation detaches it again by setting the global
scope's client to the SDK's ``NonRecordingClient``, so captures stop instead of
being routed anywhere.

Outbound payloads are bounded at the source instead of being rebuilt: the
client options disable the SDK's own integrations, PII, breadcrumbs, and local
variables, and this module only ever attaches the fields it reads from MWU
state.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import io
import json
import logging
import math
import platform
import random
import re
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

import sentry_sdk
from PIL import Image
from sentry_sdk import logger as sentry_logger
from sentry_sdk.tracing import Span
from sentry_sdk.utils import BadDsn, Dsn

import settings_io
from models.settings import SettingsModel, TelemetryConsent
from services import runtime_info

logger = logging.getLogger("mwu.telemetry")

# These are the only structured log names emitted by this service.
_ALLOWED_LOG_EVENTS = frozenset(
    {
        "mwu.run.started",
        "mwu.run.finished",
        "mwu.task.finished",
        "mwu.node.result",
        "mwu.execution.rejected",
        "mwu.error",
    }
)

_ALLOWED_ORIGINS = frozenset({"manual", "in_app", "native"})
_ALLOWED_RESULTS = frozenset(
    {"success", "failed", "stopped", "ok", "internal_error", "cancelled"}
)
# MWU run/task results map onto the narrower set of Sentry span statuses.
_SENTRY_STATUS = {"success": "ok", "failed": "internal_error", "stopped": "cancelled"}
# Sentry environment tags are tokens (``production``, ``beta``), never prose.
_ENVIRONMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")


def _observational(method):
    """Make one telemetry entry point total.

    Telemetry is strictly observational: a broken client must never alter task
    execution, so every public entry point swallows its own failures instead of
    making callers guard each call.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            self._record_local_warning("telemetry_call_failed")
            logger.debug("telemetry call failed", exc_info=True)
            return None

    return wrapper


@dataclass
class _TaskHandle:
    run_id: str
    task_name: str
    pi_entry: str
    epoch: int
    span: Span | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished: bool = False
    # Set by ``_open_task``.  An inert handle (inactive service) stays False so
    # closing it cannot emit a span, a log, or an error event.
    opened: bool = False
    result: str = "success"
    error_code: str | None = None
    exception: BaseException | None = None
    controller: Any | None = None


@dataclass
class _NodeHandle:
    run_id: str
    task_name: str | None
    epoch: int
    span: Span | None = None
    started_at: float = field(default_factory=time.monotonic)
    message_type: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    finished: bool = False
    opened: bool = False
    # ``None`` lets the close path derive the result from the message type.
    result: str | None = None


@dataclass
class _RunHandle:
    run_id: str
    origin: str
    task_names: list[str]
    epoch: int
    transaction: Span | None = None
    started_at: float = field(default_factory=time.monotonic)
    tasks: dict[str, _TaskHandle] = field(default_factory=dict)
    diagnostics: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=100)
    )
    errors: set[str] = field(default_factory=set)
    controller_type: str | None = None
    resource_name: str | None = None


class TelemetryConsentStaleError(ValueError):
    """The UI consent dialog targeted an older interface DSN."""


@contextmanager
def task_span(
    telemetry: "TelemetryService | None",
    run_id: str | None,
    task_name: str,
    pi_entry: str,
    *,
    controller: Callable[[], Any] | None = None,
) -> Iterator[_TaskHandle]:
    """Open a task span for the duration of the block.

    The yielded handle carries the outcome: set ``result`` (``success`` /
    ``failed`` / ``stopped``) and ``error_code`` inside the block.  An
    exception escaping the block is recorded as a failure.  Closing the block
    finishes the span and, when the result is ``failed``, reports the matching
    error event with ``controller()`` supplying the failure-attachment source.

    A missing, unstarted, or inactive service yields an inert handle, so call
    sites never branch on telemetry state.
    """

    handle = _TaskHandle(
        run_id=run_id or "", task_name=task_name, pi_entry=pi_entry, epoch=-1
    )
    if telemetry is not None and run_id is not None:
        opened = telemetry._open_task(run_id, task_name, pi_entry)
        if opened is not None:
            handle = opened
    try:
        yield handle
    except BaseException as exc:
        if handle.result == "success":
            handle.result = "failed"
            handle.error_code = handle.error_code or "mwu.task.failed"
            handle.exception = exc
        raise
    finally:
        if telemetry is not None:
            if handle.controller is None and controller is not None:
                handle.controller = controller()
            telemetry._close_task(handle)


@contextmanager
def node_span(
    telemetry: "TelemetryService | None",
    run_id: str | None,
    *,
    task_name: str | None = None,
    message_type: str | None = None,
    details: dict[str, Any] | None = None,
    trace_allowed: bool = False,
) -> Iterator[_NodeHandle]:
    """Open a node span for the duration of the block.

    The result defaults to the one implied by ``message_type``; set
    ``handle.result`` inside the block to override it.
    """

    handle = _NodeHandle(
        run_id=run_id or "",
        task_name=task_name,
        epoch=-1,
        message_type=message_type,
    )
    if telemetry is not None and run_id is not None:
        opened = telemetry._open_node(
            run_id,
            task_name=task_name,
            message_type=message_type,
            details=details,
            trace_allowed=trace_allowed,
        )
        if opened is not None:
            handle = opened
    try:
        yield handle
    finally:
        if telemetry is not None:
            telemetry._close_node(handle)


class TelemetryService:
    """Opt-in telemetry backend publishing through Sentry's global client."""

    def __init__(
        self,
        interface: Any,
        settings: SettingsModel | None = None,
        settings_path: Path | None = None,
        *,
        build_allowed: bool | None = None,
        client_factory: Any | None = None,
    ) -> None:
        self.interface = interface
        self.settings_path = (
            Path(settings_path)
            if settings_path is not None
            else settings_io.default_settings_path()
        )
        if settings is None:
            try:
                settings = settings_io.load_settings_model(self.settings_path)
            except Exception:
                settings = SettingsModel()
        self._settings = settings
        # The interface is loaded once during startup and never reloaded, so the
        # Sentry target, the tracing switches, and the build gate are resolved
        # exactly once instead of on every capture.
        self._sentry = getattr(getattr(interface, "telemetry", None), "sentry", None)
        self._tracing = self._resolve_tracing()
        self._trace_rate = (
            self._resolve_sample_rate("traces_sample_rate") if self._tracing else 0.0
        )
        self._attachment_rate = self._resolve_sample_rate(
            "failure_attachments_sample_rate"
        )
        self._environment = self._resolve_environment()
        self._build_allowed = (
            bool(build_allowed)
            if build_allowed is not None
            else self._resolve_build_allowed()
        )
        self._dsn = self._parse_dsn()
        self._config_id = self._compute_config_id()
        self._client_factory = client_factory or sentry_sdk.Client
        self._lock = threading.RLock()
        self._client: Any | None = None
        self._client_epoch: int | None = None
        self._epoch = 0
        self._logs_enabled = False
        self._runs: dict[str, _RunHandle] = {}
        self._saved_sys_excepthook: Any | None = None
        self._saved_threading_excepthook: Any | None = None
        self._saved_loop_handlers: dict[asyncio.AbstractEventLoop, Any] = {}
        self._handlers_installed = False
        self._last_warning_at: dict[str, float] = {}
        self._common_tags = self._build_common_tags()

        # No client is created until consent is explicit, the target matches,
        # and this is an allowed packaged build.
        if self._authorized():
            self._enable_client()

    # ------------------------------------------------------------------
    # Configuration and consent
    # ------------------------------------------------------------------

    @property
    def settings(self) -> SettingsModel:
        return self._settings

    def _is_configured(self) -> bool:
        return self._dsn is not None

    def _is_build_allowed(self) -> bool:
        return self._build_allowed

    @staticmethod
    def _resolve_build_allowed() -> bool:
        try:
            return bool(runtime_info.telemetry_build_allowed())
        except Exception:
            return False

    def _resolve_tracing(self) -> bool:
        tracing = getattr(self._sentry, "tracing", True)
        return True if tracing is None else bool(tracing)

    def _resolve_sample_rate(self, field: str) -> float:
        """Clamp one interface sample rate into ``[0, 1]``; invalid means zero."""

        rate = getattr(self._sentry, field, 1.0)
        if rate is None:
            return 1.0
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            return 0.0
        return rate if math.isfinite(rate) and 0 <= rate <= 1 else 0.0

    def _resolve_environment(self) -> str:
        """PI ``telemetry.sentry.environment``; malformed values fall back."""

        raw = getattr(self._sentry, "environment", None)
        value = raw.strip() if isinstance(raw, str) else ""
        return value if _ENVIRONMENT_RE.fullmatch(value) else "production"

    def _parse_dsn(self) -> Dsn | None:
        dsn = getattr(self._sentry, "dsn", None)
        if not isinstance(dsn, str) or not dsn.strip():
            return None
        try:
            return Dsn(dsn.strip())
        except (BadDsn, ValueError, TypeError) as exc:
            logger.warning("telemetry_invalid_dsn: %s", type(exc).__name__)
            return None

    def _normalized_dsn(self) -> str:
        parsed = self._dsn
        if parsed is None:
            return ""
        # DSN credentials are included only in the local hash.  The recipient
        # and all outbound events are scrubbed separately.
        userinfo = parsed.public_key
        if parsed.secret_key:
            userinfo += "@" + parsed.secret_key
        return (
            f"{parsed.scheme.lower()}://{userinfo}@{parsed.host.lower()}"
            f"{parsed.netloc[len(parsed.host) :]}{parsed.path}{parsed.project_id}"
        )

    def _compute_config_id(self) -> str:
        if self._dsn is None:
            return ""
        name = str(getattr(self.interface, "name", "")).strip()
        material = name + self._normalized_dsn()
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _recipient(self) -> dict[str, str] | None:
        parsed = self._dsn
        if parsed is None:
            return None
        return {
            "project": str(getattr(self.interface, "name", "")),
            "host": parsed.host,
            "path": parsed.path.rstrip("/"),
            "project_id": parsed.project_id,
        }

    def _authorized(self) -> bool:
        consent = getattr(self._settings, "telemetry", None)
        if not isinstance(consent, TelemetryConsent):
            return False
        return (
            consent.consent == "granted"
            and bool(self._config_id)
            and consent.configId == self._config_id
            and self._build_allowed
            and self._dsn is not None
        )

    def _is_active(self) -> bool:
        with self._lock:
            client = self._client
            return bool(
                self._authorized()
                and client is not None
                and self._client_epoch == self._epoch
                # An embedded Agent that installs its own client takes the
                # global slot; report inactive rather than claiming otherwise.
                and self._owns_global_client(client)
            )

    def status_payload(self) -> dict[str, Any]:
        consent = getattr(self._settings, "telemetry", None)
        if not isinstance(consent, TelemetryConsent):
            consent = TelemetryConsent()
        current_config_id = self._config_id
        consent_matches_target = bool(current_config_id) and (
            consent.configId == current_config_id
        )
        return {
            "configured": self._is_configured(),
            "buildAllowed": self._is_build_allowed(),
            "active": self._is_active(),
            "configId": current_config_id,
            "recipient": self._recipient(),
            "consent": consent.consent if consent_matches_target else "unknown",
            "failureAttachments": (
                bool(consent.failureAttachments) if consent_matches_target else False
            ),
        }

    def apply_consent(
        self,
        config_id: str,
        consent: Literal["granted", "denied"],
        failure_attachments: bool = False,
    ) -> dict[str, Any]:
        expected = self._config_id
        if not expected or config_id != expected:
            raise TelemetryConsentStaleError("遥测接收目标已变化，请重新确认")

        if consent not in {"granted", "denied"}:
            raise ValueError("无效的遥测授权状态")
        next_consent = TelemetryConsent(
            consent=consent,
            configId=expected,
            failureAttachments=bool(failure_attachments)
            if consent == "granted"
            else False,
        )
        # Merge consent into the *current disk* settings snapshot, not the
        # startup-captured self._settings.  Otherwise a consent change after
        # any other settings save would silently revert those newer settings.
        try:
            current = settings_io.load_settings_model(self.settings_path)
        except Exception:
            current = self._settings
        # Only the dedicated consent path can supply telemetry_override.  The
        # normal settings endpoint always preserves the disk value.
        next_settings = current.model_copy(update={"telemetry": next_consent})
        written = settings_io.write_settings_preserving_protected(
            self.settings_path,
            next_settings,
            telemetry_override=next_consent,
        )
        # Validation happens after the successful atomic write.  If validation
        # unexpectedly fails, the old in-memory authorization remains in force.
        validated = SettingsModel.model_validate(written)
        with self._lock:
            self._settings = validated
        if consent == "granted":
            self._enable_client()
        else:
            self._revoke()
        return self.status_payload()

    # ------------------------------------------------------------------
    # Client lifecycle and exception hooks
    # ------------------------------------------------------------------

    def _build_common_tags(self) -> dict[str, str]:
        try:
            import importlib.metadata

            maa_version = importlib.metadata.version("maafw")
        except Exception:
            maa_version = "unknown"
        return {
            "project": str(getattr(self.interface, "name", "unknown"))[:128],
            "client": f"MWU@{runtime_info.mwu_version() or 'unknown'}"[:128],
            "maafw": str(maa_version)[:128],
            "pi": str(getattr(self.interface, "version", None) or "unknown")[:128],
            "os": platform.system().lower()[:32] or "unknown",
        }

    def _sentry_options(self) -> dict[str, Any]:
        project_name = str(getattr(self.interface, "name", "unknown"))
        version = str(getattr(self.interface, "version", None) or "unknown")
        options: dict[str, Any] = {
            "dsn": str(getattr(self._sentry, "dsn", "")).strip(),
            # Master privacy switch: disables every default integration (which
            # includes the excepthook/threading/atexit ones MWU replaces with
            # its own hooks) *and* all auto-enabling integrations, so no
            # framework integration can attach request, user, or breadcrumb
            # data.  Verified against sentry-sdk 2.68.1: the resulting client
            # carries zero integrations.
            "default_integrations": False,
            "send_default_pii": False,
            "attach_stacktrace": False,
            "include_local_variables": False,
            "include_source_context": False,
            "server_name": "",
            "auto_session_tracking": False,
            "send_client_reports": False,
            "max_breadcrumbs": 0,
            "propagate_traces": False,
            "trace_propagation_targets": [],
            "enable_backpressure_handling": False,
            "profiles_sample_rate": 0.0,
            "traces_sample_rate": self._trace_rate,
            "trace_lifecycle": "static",
            "release": f"{project_name}@{version}",
            "environment": self._environment,
            "debug": False,
        }
        return options

    def _enable_client(self) -> None:
        if not self._authorized():
            return
        with self._lock:
            old_client = self._client
            self._client = None
            self._client_epoch = None
            self._logs_enabled = False
            self._epoch += 1
            epoch = self._epoch
        if old_client is not None:
            # Detach before closing so the global scope never points at a
            # closed client, including when the rebuild below fails.
            self._unbind_global_client_locked(old_client)
            self._close_client(old_client, timeout=0)

        client = None
        try:
            client = self._client_factory(**self._sentry_options())
        except Exception:
            logger.warning("Sentry client 初始化失败，遥测保持关闭", exc_info=True)

        if client is None:
            return
        with self._lock:
            # A revoke/target change can race client construction.  Do not
            # adopt a client into an invalid epoch.
            if not self._authorized() or epoch != self._epoch:
                self._close_client(client, timeout=0)
                return
            self._client = client
            self._client_epoch = epoch
            self._logs_enabled = True
            # Publish through Sentry's global scope, exactly as
            # ``sentry_sdk.init`` does.  Captures, transactions, and the logger
            # resolve the client from the scope chain, so no per-capture scope
            # binding is needed.  ``_revoke`` detaches it again.
            try:
                global_scope = sentry_sdk.get_global_scope()
                global_scope.set_client(client)
                global_scope.set_tags(self._common_tags)
            except Exception:
                self._client = None
                self._client_epoch = None
                self._logs_enabled = False
                self._unbind_global_client_locked(client)
                self._close_client(client, timeout=0)
                logger.warning("Sentry client 发布失败，遥测保持关闭", exc_info=True)
                return
        self._install_exception_handlers()

    @staticmethod
    def _close_client(client: Any, *, timeout: float) -> None:
        try:
            client.close(timeout=timeout)
        except Exception:
            logger.debug("telemetry client close failed", exc_info=True)

    @staticmethod
    def _owns_global_client(client: Any) -> bool:
        return sentry_sdk.get_global_scope().client is client

    def _unbind_global_client_locked(self, client: Any) -> None:
        """Remove only a client this service previously published.

        An embedded Agent may intentionally replace the global client.  Never
        close or overwrite that replacement as part of MWU lifecycle cleanup.
        """

        try:
            global_scope = sentry_sdk.get_global_scope()
            if global_scope.client is not client:
                return
            for key in self._common_tags:
                global_scope.remove_tag(key)
            global_scope.set_client(None)
        except Exception:
            logger.debug("telemetry global client unbind failed", exc_info=True)

    def _revoke(self) -> None:
        """Detach the client before closing so nothing new is captured."""

        with self._lock:
            self._epoch += 1
            old_client = self._client
            self._client = None
            self._client_epoch = None
            self._logs_enabled = False
            self._clear_run_buffers_locked()
            if old_client is not None:
                self._unbind_global_client_locked(old_client)
        self._restore_exception_handlers()
        if old_client is not None:
            self._close_client(old_client, timeout=0)

    @_observational
    def flush_and_close_limited(self) -> None:
        """Close on normal exit, flushing for at most two seconds if active."""

        with self._lock:
            active = self._authorized() and self._client is not None
            client = self._client
            self._logs_enabled = False
            self._clear_run_buffers_locked()
        self._restore_exception_handlers()
        if client is not None:
            # Normal shutdown is allowed a bounded flush, so the global client
            # stays installed while Client.close drains its queue.
            self._close_client(client, timeout=2.0 if active else 0)
        with self._lock:
            if self._client is client:
                self._epoch += 1
                self._client = None
                self._client_epoch = None
                if client is not None:
                    self._unbind_global_client_locked(client)

    def _can_send_epoch(self, epoch: int) -> bool:
        with self._lock:
            client = self._client
            return bool(
                epoch == self._epoch
                and client is not None
                and self._client_epoch == epoch
                and self._authorized()
                and self._owns_global_client(client)
            )

    def _install_exception_handlers(self) -> None:
        with self._lock:
            if self._handlers_installed or not self._is_active():
                return
            self._saved_sys_excepthook = sys.excepthook
            sys.excepthook = self._sys_excepthook
            if hasattr(threading, "excepthook"):
                self._saved_threading_excepthook = threading.excepthook
                threading.excepthook = self._threading_excepthook
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                self._saved_loop_handlers[loop] = loop.get_exception_handler()
                loop.set_exception_handler(self._loop_exception_handler)
            self._handlers_installed = True

    def _restore_exception_handlers(self) -> None:
        with self._lock:
            if not self._handlers_installed:
                return
            if (
                self._saved_sys_excepthook is not None
                and sys.excepthook == self._sys_excepthook
            ):
                sys.excepthook = self._saved_sys_excepthook
            if (
                self._saved_threading_excepthook is not None
                and getattr(threading, "excepthook", None) == self._threading_excepthook
            ):
                threading.excepthook = self._saved_threading_excepthook
            for loop, handler in list(self._saved_loop_handlers.items()):
                try:
                    if (
                        not loop.is_closed()
                        and loop.get_exception_handler() == self._loop_exception_handler
                    ):
                        loop.set_exception_handler(handler)
                except Exception:
                    pass
            self._saved_loop_handlers.clear()
            self._saved_sys_excepthook = None
            self._saved_threading_excepthook = None
            self._handlers_installed = False

    def _sys_excepthook(self, exc_type, exc_value, exc_traceback) -> None:
        try:
            if isinstance(exc_value, BaseException):
                self._capture_unhandled(
                    exc_value,
                    error_code="unhandled_exception",
                    traceback=exc_traceback,
                )
        except Exception:
            logger.debug("telemetry sys.excepthook failed", exc_info=True)
        previous = self._saved_sys_excepthook
        if previous is not None and previous is not self._sys_excepthook:
            previous(exc_type, exc_value, exc_traceback)

    def _threading_excepthook(self, args) -> None:
        try:
            value = getattr(args, "exc_value", None)
            if isinstance(value, BaseException):
                self._capture_unhandled(
                    value,
                    error_code="unhandled_exception",
                    traceback=getattr(args, "exc_traceback", None),
                )
        except Exception:
            logger.debug("telemetry threading.excepthook failed", exc_info=True)
        previous = self._saved_threading_excepthook
        if previous is not None and previous is not self._threading_excepthook:
            previous(args)

    def _loop_exception_handler(self, loop, context) -> None:
        try:
            value = context.get("exception") if isinstance(context, dict) else None
            if isinstance(value, BaseException):
                self._capture_unhandled(value, error_code="unhandled_exception")
            else:
                self._record_local_warning("asyncio_unhandled_exception")
        except Exception:
            logger.debug("telemetry asyncio exception handler failed", exc_info=True)
        previous = self._saved_loop_handlers.get(loop)
        if previous is not None and previous is not self._loop_exception_handler:
            previous(loop, context)
        else:
            try:
                loop.default_exception_handler(context)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Structured logs and tracing lifecycle
    # ------------------------------------------------------------------

    def _capture_log(
        self, event_name: str, attrs: dict[str, Any], *, severity: str = "info"
    ) -> None:
        if event_name not in _ALLOWED_LOG_EVENTS:
            return
        with self._lock:
            client = self._client
            epoch = self._client_epoch
            if (
                not self._logs_enabled
                or client is None
                or epoch is None
                or not self._authorized()
            ):
                return
            attributes: dict[str, Any] = {"event_name": event_name, **attrs}
        if not self._can_send_epoch(epoch):
            return
        try:
            self._emit_log(severity, event_name, attributes)
        except Exception:
            self._record_local_warning("log_capture_failed")

    @staticmethod
    def _emit_log(severity: str, event_name: str, attributes: dict[str, Any]) -> None:
        """Emit one log through the installed global client."""

        capture = getattr(sentry_logger, severity, sentry_logger.info)
        capture(event_name, attributes=attributes)

    @_observational
    def start_run(
        self,
        run_id: str,
        origin: str,
        task_names: list[str] | None = None,
    ) -> _RunHandle | None:
        if not self._is_active():
            return None
        origin = origin if origin in _ALLOWED_ORIGINS else "in_app"
        task_names = [
            str(name)[:256] for name in (task_names or []) if isinstance(name, str)
        ]
        with self._lock:
            existing = self._runs.get(run_id)
            if existing is not None:
                return existing
            epoch = self._epoch

        transaction: Span | None = None
        if self._trace_rate > 0:
            try:
                transaction = sentry_sdk.start_transaction(
                    name="mwu.run",
                    op="mwu.run",
                    origin="manual",
                )
                for key, value in self._common_tags.items():
                    transaction.set_tag(key, value)
                transaction.set_data("run_id", str(run_id)[:128])
                transaction.set_data("origin", origin)
            except Exception:
                logger.debug("telemetry run transaction failed", exc_info=True)
                transaction = None
        handle = _RunHandle(
            run_id=str(run_id),
            origin=origin,
            task_names=task_names,
            epoch=epoch,
            transaction=transaction,
        )
        with self._lock:
            if not self._can_send_epoch(epoch):
                return None
            self._runs[run_id] = handle
        if self._tracing:
            self._capture_log(
                "mwu.run.started",
                {
                    "run_id": run_id,
                    "origin": origin,
                    "task_name": task_names[0] if task_names else None,
                },
            )
        return handle

    @_observational
    def finish_run(self, run_id: str, result: str) -> None:
        with self._lock:
            handle = self._runs.pop(run_id, None)
        if handle is None:
            return
        result = result if result in _ALLOWED_RESULTS else "failed"
        sentry_result = _SENTRY_STATUS.get(result, result)
        duration_ms = int(max(0.0, time.monotonic() - handle.started_at) * 1000)
        if handle.transaction is not None:
            try:
                handle.transaction.set_data("result", sentry_result)
                handle.transaction.set_data("duration_ms", duration_ms)
                handle.transaction.set_status(sentry_result)
                if self._can_send_epoch(handle.epoch):
                    handle.transaction.finish()
            except Exception:
                logger.debug("telemetry run transaction finish failed", exc_info=True)
        if self._tracing:
            self._capture_log(
                "mwu.run.finished",
                {
                    "run_id": run_id,
                    "origin": handle.origin,
                    "task_name": handle.task_names[0] if handle.task_names else None,
                    "controller_type": handle.controller_type,
                    "resource_name": handle.resource_name,
                    "result": result,
                    "duration_ms": duration_ms,
                },
            )
        handle.diagnostics.clear()

    @_observational
    def set_run_context(
        self,
        run_id: str,
        *,
        controller_type: str | None = None,
        resource_name: str | None = None,
    ) -> None:
        """Attach controlled execution context once preparation has a payload."""

        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            if controller_type is not None:
                run.controller_type = controller_type
            if resource_name is not None:
                run.resource_name = resource_name

    @_observational
    def _open_task(
        self, run_id: str, task_name: str, pi_entry: str
    ) -> _TaskHandle | None:
        """Open a task span inside an active run; ``None`` means no span."""

        if not self._is_active():
            return None
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            task = _TaskHandle(
                run_id=run_id,
                task_name=str(task_name)[:256],
                pi_entry=str(pi_entry)[:256],
                epoch=run.epoch,
                opened=True,
            )
            if run.transaction is not None:
                try:
                    task.span = run.transaction.start_child(
                        op="maa.task", name="maa.task", origin="manual"
                    )
                    task.span.set_data("task_name", task.task_name)
                    task.span.set_data("pi_entry", task.pi_entry)
                except Exception:
                    logger.debug("telemetry task span failed", exc_info=True)
                    task.span = None
            run.tasks[task.task_name] = task
            return task

    @_observational
    def _close_task(self, handle: _TaskHandle) -> None:
        """Finish a task span and report its failure, if any."""

        if not handle.opened or handle.finished:
            return
        handle.finished = True
        status = handle.result if handle.result in _ALLOWED_RESULTS else "failed"
        duration_ms = int(max(0.0, time.monotonic() - handle.started_at) * 1000)
        with self._lock:
            run = self._runs.get(handle.run_id)
            controller_type = run.controller_type if run is not None else None
            resource_name = run.resource_name if run is not None else None
        if handle.span is not None:
            try:
                handle.span.set_data("task_name", handle.task_name)
                handle.span.set_data("result", status)
                handle.span.set_data("duration_ms", duration_ms)
                if handle.error_code:
                    handle.span.set_data("error_code", handle.error_code)
                handle.span.set_status(_SENTRY_STATUS.get(status, status))
                if self._can_send_epoch(handle.epoch):
                    handle.span.finish()
            except Exception:
                logger.debug("telemetry task span finish failed", exc_info=True)
        if self._tracing:
            self._capture_log(
                "mwu.task.finished",
                {
                    "run_id": handle.run_id,
                    "task_name": handle.task_name,
                    "pi_entry": handle.pi_entry,
                    "controller_type": controller_type,
                    "resource_name": resource_name,
                    "result": status,
                    "duration_ms": duration_ms,
                    "error_code": handle.error_code,
                },
                severity="error" if status == "failed" else "info",
            )
        if status == "failed":
            self._capture_error(
                handle.run_id,
                error_code=handle.error_code or "mwu.task.failed",
                exception=handle.exception,
                task_name=handle.task_name,
                controller=handle.controller,
                attach=True,
            )
        with self._lock:
            run = self._runs.get(handle.run_id)
            if run is not None:
                run.tasks.pop(handle.task_name, None)

    @_observational
    def _open_node(
        self,
        run_id: str,
        *,
        task_name: str | None = None,
        message_type: str | None = None,
        details: dict[str, Any] | None = None,
        trace_allowed: bool = False,
    ) -> _NodeHandle | None:
        """Open a node span under the current task, when tracing allows it."""

        if not trace_allowed or not self._tracing or not self._is_active():
            return None
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            task_handle = run.tasks.get(task_name or "")
            parent = task_handle.span if task_handle is not None else run.transaction
            span = None
            if parent is not None:
                try:
                    span = parent.start_child(
                        op="maa.node", name="maa.node", origin="manual"
                    )
                except Exception:
                    logger.debug("telemetry node span failed", exc_info=True)
            attrs: dict[str, Any] = {
                "run_id": run_id,
                "task_name": task_name,
                "message_type": message_type,
            }
            if isinstance(details, dict):
                for key in ("name", "task_id", "node_id", "reco_id", "action_id"):
                    if key in details:
                        attrs[key] = details[key]
            node = _NodeHandle(
                run_id=run_id,
                task_name=task_name,
                epoch=run.epoch,
                span=span,
                message_type=message_type,
                attributes=attrs,
                opened=True,
            )
            if span is not None:
                for key, value in attrs.items():
                    span.set_data(key, value)
            return node

    @_observational
    def _close_node(self, handle: _NodeHandle) -> None:
        """Finish a node span, log its result, and buffer a diagnostic record."""

        if not handle.opened or handle.finished:
            return
        handle.finished = True
        result = handle.result
        if result is None:
            # MAA reports node failures through the message type.
            result = (
                "failed"
                if (handle.message_type or "").endswith(".Failed")
                else "success"
            )
        if result not in _ALLOWED_RESULTS:
            result = "failed" if str(result).endswith("Failed") else "success"
        duration_ms = int(max(0.0, time.monotonic() - handle.started_at) * 1000)
        if handle.span is not None:
            try:
                handle.span.set_data("result", result)
                handle.span.set_data("duration_ms", duration_ms)
                handle.span.set_status("internal_error" if result == "failed" else "ok")
                if self._can_send_epoch(handle.epoch):
                    handle.span.finish()
            except Exception:
                logger.debug("telemetry node span finish failed", exc_info=True)
        if self._tracing:
            self._capture_log(
                "mwu.node.result",
                {
                    **handle.attributes,
                    "result": result,
                    "duration_ms": duration_ms,
                },
                severity="error" if result == "failed" else "info",
            )
        self._record_diagnostic(
            handle.run_id,
            message_type=handle.message_type,
            task_name=handle.task_name,
            result=result,
            **{
                key: value
                for key, value in handle.attributes.items()
                if key in {"name", "task_id", "node_id", "reco_id", "action_id"}
            },
        )

    @_observational
    def record_execution_rejected(
        self,
        *,
        run_id: str | None = None,
        origin: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._capture_log(
            "mwu.execution.rejected",
            {"run_id": run_id, "origin": origin, "error_code": error_code},
            severity="warning",
        )

    # ------------------------------------------------------------------
    # Errors, diagnostics, and failure attachments
    # ------------------------------------------------------------------

    def _record_diagnostic(
        self,
        run_id: str,
        *,
        message_type: str | None = None,
        task_name: str | None = None,
        result: str | None = None,
        **attrs: Any,
    ) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            record: dict[str, Any] = {
                "time": int(time.time()),
                "message_type": message_type,
                "task_name": task_name,
                "result": result,
                **attrs,
            }
            run.diagnostics.append(record)

    def _diagnostics_bytes(self, run: _RunHandle) -> bytes | None:
        lines: list[bytes] = []
        used = 0
        # Preserve the most recent records under the byte budget.
        for item in reversed(list(run.diagnostics)):
            try:
                line = (
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
                ).encode("utf-8")
            except Exception:
                continue
            if len(line) > 64 * 1024:
                continue
            if used + len(line) > 64 * 1024:
                continue
            lines.append(line)
            used += len(line)
        if not lines:
            return None
        lines.reverse()
        return b"".join(lines)

    @staticmethod
    def _copy_cached_image(controller: Any) -> Any | None:
        """Copy the failure-time frame before the controller mutates it again."""

        try:
            image = getattr(controller, "cached_image", None)
            if image is None:
                return None
            if isinstance(image, Image.Image):
                return image.copy()
            copier = getattr(image, "copy", None)
            return copier() if callable(copier) else image
        except Exception:
            return None

    @staticmethod
    def _encode_failure_image(image: Any) -> bytes | None:
        try:
            if isinstance(image, Image.Image):
                output = image.convert("RGB")
            elif isinstance(image, (bytes, bytearray, memoryview)):
                output = Image.open(io.BytesIO(bytes(image))).convert("RGB")
            else:
                # Maa images are numpy BGR arrays.  Import lazily so tests and
                # no-device startup do not pay the conversion cost.
                import numpy as np

                array = np.asarray(image)
                if array.ndim == 2:
                    output = Image.fromarray(array.astype("uint8"), mode="L").convert(
                        "RGB"
                    )
                elif array.ndim == 3 and array.shape[2] >= 3:
                    output = Image.fromarray(
                        array[:, :, :3][:, :, ::-1].astype("uint8"), mode="RGB"
                    )
                else:
                    return None
            if output.width <= 0 or output.height <= 0:
                return None
            if max(output.width, output.height) > 1920:
                output.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            output.save(buffer, format="JPEG", quality=80)
            encoded = buffer.getvalue()
            if len(encoded) > 2 * 1024 * 1024:
                return None
            return encoded
        except Exception:
            return None

    def _failure_attachments(
        self,
        run: _RunHandle,
        *,
        controller: Any | None,
    ) -> list[tuple[str, bytes, str]]:
        with self._lock:
            if (
                not self._authorized()
                or self._client is None
                or self._client_epoch != run.epoch
            ):
                return []
            if not self._settings.telemetry.failureAttachments:
                return []
            if self._attachment_rate <= 0 or random.random() >= self._attachment_rate:
                return []
            # Copy pixels while still in the failure callback.  Encoding can
            # then happen without borrowing a mutable controller image.
            copied_image = (
                self._copy_cached_image(controller) if controller is not None else None
            )
            diagnostics = self._diagnostics_bytes(run)
            epoch = run.epoch
        attachments: list[tuple[str, bytes, str]] = []
        if copied_image is not None:
            image_bytes = self._encode_failure_image(copied_image)
            if image_bytes is not None:
                attachments.append(("failure.jpg", image_bytes, "image/jpeg"))
        if not self._can_send_epoch(epoch):
            return []
        if diagnostics is not None:
            attachments.append(("diagnostics.jsonl", diagnostics, "application/json"))
        return attachments

    @_observational
    def _capture_error(
        self,
        run_id: str | None,
        *,
        error_code: str,
        exception: BaseException | None = None,
        traceback: TracebackType | None = None,
        task_name: str | None = None,
        controller: Any | None = None,
        attach: bool = False,
    ) -> None:
        if exception is not None and isinstance(
            exception, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
        ):
            return
        with self._lock:
            epoch = self._client_epoch
        if epoch is None or not self._can_send_epoch(epoch):
            return
        run: _RunHandle | None = None
        with self._lock:
            if run_id is not None:
                run = self._runs.get(run_id)
                if run is not None and error_code in run.errors:
                    return
                if run is not None:
                    run.errors.add(error_code)
        if exception is None:
            exception = RuntimeError(error_code)
        attachments = (
            self._failure_attachments(run, controller=controller)
            if attach and run is not None
            else []
        )

        captured_exception: Any = exception
        if traceback is not None or exception.__traceback__ is not None:
            captured_exception = (
                type(exception),
                exception,
                traceback or exception.__traceback__,
            )
        scope = sentry_sdk.get_current_scope()
        scope.set_context(
            "mwu",
            {
                "run_id": run_id,
                "task_name": task_name,
                "error_code": error_code,
            },
        )
        for filename, payload, content_type in attachments:
            scope.add_attachment(
                bytes=payload,
                filename=filename,
                content_type=content_type,
                add_to_transactions=False,
            )
        scope.capture_exception(captured_exception)
        self._capture_log(
            "mwu.error",
            {
                "run_id": run_id,
                "task_name": task_name,
                "error_code": error_code,
                "result": "failed",
            },
            severity="error",
        )

    @_observational
    def _capture_unhandled(
        self,
        exception: BaseException,
        *,
        error_code: str = "mwu.error",
        traceback: TracebackType | None = None,
    ) -> None:
        """Capture an exception raised outside any MWU run, such as in a hook."""

        self._capture_error(
            None,
            error_code=error_code,
            exception=exception,
            traceback=traceback,
        )

    @_observational
    def capture_prepare_failed(
        self,
        run_id: str,
        exception: BaseException | None = None,
        *,
        task_name: str | None = None,
    ) -> None:
        self._capture_error(
            run_id,
            error_code="mwu.execution.prepare_failed",
            exception=exception,
            task_name=task_name,
        )

    @_observational
    def capture_task_failed(
        self,
        run_id: str | None,
        task_name: str,
        exception: BaseException | None = None,
        *,
        controller: Any | None = None,
    ) -> None:
        """Report a task failure raised outside any task span.

        Failures inside a span are reported by ``_close_task``; this covers the
        pre-task window (event emission, interface lookup) where no span exists.
        """

        self._capture_error(
            run_id,
            error_code="mwu.task.failed",
            exception=exception,
            task_name=task_name,
            controller=controller,
            attach=True,
        )

    def _clear_run_buffers_locked(self) -> None:
        for run in self._runs.values():
            run.diagnostics.clear()
            run.tasks.clear()
        self._runs.clear()

    def _record_local_warning(self, key: str) -> None:
        now = time.monotonic()
        last = self._last_warning_at.get(key, 0.0)
        if now - last >= 60.0:
            self._last_warning_at[key] = now
            logger.warning("telemetry diagnostic: %s", key)


__all__ = [
    "TelemetryConsentStaleError",
    "TelemetryService",
    "node_span",
    "task_span",
]
