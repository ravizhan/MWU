"""Opt-in, isolated Sentry telemetry for MWU.

The service deliberately does not use :mod:`sentry_sdk`'s global hub.  MWU can
run an embedded Agent which owns its own Sentry client, so every event, span,
and log created here is scoped to this service's client only.
"""

from __future__ import annotations

import asyncio
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
import traceback as traceback_module
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from PIL import Image
import sentry_sdk
from sentry_sdk import Scope
from sentry_sdk.tracing import Span, Transaction
from sentry_sdk.transport import HttpTransport
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

# Attributes accepted in structured logs, transactions, and diagnostics.
_ALLOWED_ATTRIBUTES = frozenset(
    {
        "run_id",
        "origin",
        "task_name",
        "pi_entry",
        "controller_type",
        "resource_name",
        "result",
        "duration_ms",
        "error_code",
        "message_type",
        "name",
        "task_id",
        "node_id",
        "reco_id",
        "action_id",
    }
)
_ALLOWED_TAGS = frozenset({"project", "client", "maafw", "pi", "os"})
_ALLOWED_ERROR_CODES = frozenset(
    {
        "mwu.execution.prepare_failed",
        "mwu.task.failed",
        "mwu.error",
        "mwu.execution.rejected",
        "telemetry_invalid_dsn",
        "runtime_error",
        "config_error",
        "permission_required",
        "resource_unavailable",
        "device_unavailable",
        "task_start_failed",
        "unhandled_exception",
        "busy_manual",
        "busy_scheduled",
        "skipped_busy_manual",
        "skipped_busy_scheduled",
        "skipped_update_in_progress",
        "update_in_progress",
    }
)
_ALLOWED_ORIGINS = frozenset({"manual", "in_app", "native"})
_ALLOWED_RESULTS = frozenset(
    {"success", "failed", "stopped", "ok", "internal_error", "cancelled"}
)


def _safe_string(value: Any, *, max_length: int = 256) -> str | None:
    """Return a short scalar string, never recursively serializing objects."""

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        return value[:max_length]
    if isinstance(value, bool) or isinstance(value, int):
        return str(value)[:max_length]
    if isinstance(value, float) and math.isfinite(value):
        return str(value)[:max_length]
    return None


def _safe_identifier(value: Any, *, max_length: int = 256) -> str | None:
    value = _safe_string(value, max_length=max_length)
    if value is None:
        return None
    # Identifiers are allowed, but a path is not.  Keep only the final segment
    # if a native SDK accidentally reports a source path as a function/name.
    value = value.replace("\\", "/").rsplit("/", 1)[-1]
    return value[:max_length] or None


def _safe_code(value: Any, default: str = "runtime_error") -> str:
    value = _safe_string(value, max_length=96)
    return value if value in _ALLOWED_ERROR_CODES else default


def _safe_origin(value: Any) -> str | None:
    value = _safe_string(value, max_length=32)
    return value if value in _ALLOWED_ORIGINS else None


def _safe_result(value: Any) -> str | None:
    value = _safe_string(value, max_length=32)
    return value if value in _ALLOWED_RESULTS else None


def _safe_timestamp(value: Any) -> float | None:
    if isinstance(value, datetime):
        try:
            value = value.timestamp()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if math.isfinite(value):
            return value
    return None


def _client_option(client: Any, key: str) -> Any:
    options = getattr(client, "options", None)
    if isinstance(options, dict):
        return options.get(key)
    return None


def _safe_attribute(name: str, value: Any) -> Any:
    """Whitelist one known attribute and coerce it to a bounded scalar."""

    if name not in _ALLOWED_ATTRIBUTES or value is None:
        return None
    if name == "error_code":
        return _safe_code(value)
    if name == "origin":
        return _safe_origin(value)
    if name == "result":
        return _safe_result(value)
    if name == "duration_ms":
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return max(0, min(int(value), 86_400_000))
        return None
    if name in {"run_id", "task_id", "node_id", "reco_id", "action_id"}:
        return _safe_string(value, max_length=128)
    if name in {"task_name", "pi_entry", "controller_type", "resource_name", "name"}:
        raw = _safe_string(value, max_length=256)
        if raw is None or "/" in raw or "\\" in raw:
            return None
        return raw
    return _safe_identifier(value, max_length=256)


def _common_event_fields(event: dict[str, Any]) -> dict[str, Any]:
    """Copy only harmless SDK envelope fields into a scrubbed event."""

    result: dict[str, Any] = {}
    event_id = _safe_string(event.get("event_id"), max_length=64)
    if event_id and re.fullmatch(r"[0-9a-fA-F]{32}", event_id):
        result["event_id"] = event_id
    platform_name = _safe_string(event.get("platform"), max_length=32)
    if platform_name == "python":
        result["platform"] = platform_name
    level = _safe_string(event.get("level"), max_length=16)
    if level in {"debug", "info", "warning", "error", "fatal"}:
        result["level"] = level
    # Release is attached by the service's client options.  Preserve only the
    # generated ``project@version`` shape; never copy arbitrary user text.
    release = _safe_string(event.get("release"), max_length=128)
    if release and "@" in release and not any(c in release for c in "\\/\r\n"):
        result["release"] = release
    if event.get("environment") == "production":
        result["environment"] = "production"

    tags = event.get("tags")
    if isinstance(tags, dict):
        safe_tags: dict[str, str] = {}
        for key in _ALLOWED_TAGS:
            value = _safe_string(tags.get(key), max_length=128)
            if value:
                safe_tags[key] = value
        if safe_tags:
            result["tags"] = safe_tags

    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        mwu = contexts.get("mwu")
        if isinstance(mwu, dict):
            safe_mwu: dict[str, Any] = {}
            for key in _ALLOWED_ATTRIBUTES:
                value = _safe_attribute(key, mwu.get(key))
                if value is not None:
                    safe_mwu[key] = value
            if safe_mwu:
                result["contexts"] = {"mwu": safe_mwu}
    return result


def scrub_error_event(event: dict[str, Any], hint: dict[str, Any] | None = None):
    """Whitelist-only ``before_send`` callback.

    In particular, exception values are replaced with a controlled error code;
    only exception type and function/line stack-frame fields survive.
    """

    hint = hint or {}
    source = event if isinstance(event, dict) else {}
    result = _common_event_fields(source)
    code = _safe_code(hint.get("telemetry_error_code"))
    contexts = result.setdefault("contexts", {}).setdefault("mwu", {})
    contexts["error_code"] = code

    values = None
    exception = source.get("exception")
    if isinstance(exception, dict) and isinstance(exception.get("values"), list):
        values = exception["values"]
    if not values:
        values = [{}]

    safe_values: list[dict[str, Any]] = []
    for value in values[:8]:
        if not isinstance(value, dict):
            value = {}
        exception_type = _safe_identifier(value.get("type"), max_length=128)
        if not exception_type:
            exc_info = hint.get("exc_info")
            if isinstance(exc_info, tuple) and exc_info:
                exception_type = _safe_identifier(
                    getattr(exc_info[0], "__name__", None), max_length=128
                )
        exception_type = exception_type or "RuntimeError"
        safe_value: dict[str, Any] = {
            "type": exception_type,
            # Deliberately not the original exception value.  This controlled
            # code is useful for grouping while never exposing user text.
            "value": code,
        }
        stacktrace = value.get("stacktrace")
        frames = stacktrace.get("frames") if isinstance(stacktrace, dict) else None
        safe_frames: list[dict[str, Any]] = []
        if isinstance(frames, list):
            for frame in frames[-64:]:
                if not isinstance(frame, dict):
                    continue
                function = _safe_identifier(frame.get("function"), max_length=160)
                lineno = frame.get("lineno")
                if isinstance(lineno, bool) or not isinstance(lineno, int):
                    lineno = None
                if lineno is not None:
                    lineno = max(0, min(lineno, 10_000_000))
                if function is None and lineno is None:
                    continue
                output: dict[str, Any] = {}
                if function is not None:
                    output["function"] = function
                if lineno is not None:
                    output["lineno"] = lineno
                safe_frames.append(output)
        if safe_frames:
            safe_value["stacktrace"] = {"frames": safe_frames}
        safe_values.append(safe_value)
    result["exception"] = {"values": safe_values}
    return result


def _transaction_name(value: Any) -> str:
    value = _safe_string(value, max_length=64)
    if value == "mwu.run":
        return value
    if value == "maa.task":
        return value
    if value == "maa.node":
        return value
    # Do not echo arbitrary transaction names.  The service only creates the
    # three names above.
    return "mwu.run"


def scrub_transaction_event(event: dict[str, Any], hint: dict[str, Any] | None = None):
    """Whitelist-only ``before_send_transaction`` callback."""

    source = event if isinstance(event, dict) else {}
    result = _common_event_fields(source)
    result["type"] = "transaction"
    result["transaction"] = _transaction_name(
        source.get("transaction") or source.get("name")
    )
    status = _safe_string(source.get("status"), max_length=32)
    if status in {"ok", "internal_error", "cancelled"}:
        result["status"] = status

    for key in ("start_timestamp", "timestamp"):
        value = _safe_timestamp(source.get(key))
        if value is not None:
            result[key] = value

    data = source.get("data")
    if isinstance(data, dict):
        safe_data: dict[str, Any] = {}
        for key in _ALLOWED_ATTRIBUTES:
            value = _safe_attribute(key, data.get(key))
            if value is not None:
                safe_data[key] = value
        if safe_data:
            result["data"] = safe_data

    contexts = result.setdefault("contexts", {})
    trace = (
        source.get("contexts", {}).get("trace")
        if isinstance(source.get("contexts"), dict)
        else None
    )
    if isinstance(trace, dict):
        safe_trace: dict[str, str] = {}
        for key in ("trace_id", "span_id"):
            value = _safe_string(trace.get(key), max_length=64)
            if value and re.fullmatch(r"[0-9a-fA-F]{8,64}", value):
                safe_trace[key] = value
        if safe_trace:
            contexts["trace"] = safe_trace
    if not contexts:
        result.pop("contexts", None)

    safe_spans: list[dict[str, Any]] = []
    spans = source.get("spans")
    if isinstance(spans, list):
        for span in spans[:1000]:
            if not isinstance(span, dict):
                continue
            span_name = _safe_string(
                span.get("op") or span.get("description") or span.get("name"),
                max_length=64,
            )
            span_name = (
                span_name if span_name in {"maa.task", "maa.node"} else "maa.node"
            )
            safe_span: dict[str, Any] = {"op": span_name, "description": span_name}
            for key in ("start_timestamp", "timestamp"):
                value = _safe_timestamp(span.get(key))
                if value is not None:
                    safe_span[key] = value
            data = span.get("data")
            if isinstance(data, dict):
                safe_data: dict[str, Any] = {}
                for key in _ALLOWED_ATTRIBUTES:
                    value = _safe_attribute(key, data.get(key))
                    if value is not None:
                        safe_data[key] = value
                if safe_data:
                    safe_span["data"] = safe_data
            safe_spans.append(safe_span)
    if safe_spans:
        result["spans"] = safe_spans
    return result


def _raw_log_attribute(value: Any) -> Any:
    """Unwrap Sentry's typed attribute representation for the scrubber."""

    if isinstance(value, dict) and "value" in value and "type" in value:
        return value.get("value")
    return value


def scrub_log(log: dict[str, Any], hint: dict[str, Any] | None = None):
    """Whitelist-only ``before_send_log`` callback."""

    if not isinstance(log, dict):
        return None
    attributes = log.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    event_name = _raw_log_attribute(attributes.get("event_name"))
    if event_name is None:
        event_name = log.get("body")
    if not isinstance(event_name, str) or event_name not in _ALLOWED_LOG_EVENTS:
        return None

    safe_attributes: dict[str, Any] = {"event_name": event_name}
    for key in _ALLOWED_ATTRIBUTES:
        if key not in attributes:
            continue
        value = _safe_attribute(key, _raw_log_attribute(attributes[key]))
        if value is not None:
            safe_attributes[key] = value

    severity_text = _safe_string(log.get("severity_text"), max_length=16) or "info"
    if severity_text not in {"debug", "info", "warning", "error", "fatal"}:
        severity_text = "info"
    severity_number = log.get("severity_number")
    if isinstance(severity_number, bool) or not isinstance(severity_number, int):
        severity_number = 9
    timestamp = _safe_timestamp(log.get("time_unix_nano"))
    if timestamp is None:
        timestamp = time.time_ns()
    result: dict[str, Any] = {
        "severity_text": severity_text,
        "severity_number": max(1, min(severity_number, 24)),
        "body": event_name,
        "attributes": safe_attributes,
        "time_unix_nano": int(timestamp),
        "trace_id": None,
        "span_id": None,
    }
    # IDs are only correlation values.  Keep only bounded hexadecimal-looking
    # values so no arbitrary text can be smuggled through these fields.
    for key in ("trace_id", "span_id"):
        value = _safe_string(log.get(key), max_length=64)
        if value and re.fullmatch(r"[0-9a-fA-F-]{8,64}", value):
            result[key] = value
    return result


class EpochBoundHttpTransport(HttpTransport):
    """HttpTransport that drops queued/sending envelopes after epoch revocation."""

    _telemetry_service: "TelemetryService | None" = None
    _telemetry_epoch: int | None = None

    def __init__(
        self,
        options: dict[str, Any],
        service: "TelemetryService | None" = None,
        epoch: int | None = None,
    ) -> None:
        if service is not None:
            self._telemetry_service = service
        if epoch is not None:
            self._telemetry_epoch = epoch
        super().__init__(options)

    def _allowed(self) -> bool:
        service = self._telemetry_service
        epoch = self._telemetry_epoch
        if service is None or epoch is None:
            return False
        try:
            return service._can_send_epoch(epoch)
        except Exception:
            return False

    def capture_envelope(self, envelope) -> None:
        if not self._allowed():
            return
        try:
            super().capture_envelope(envelope)
        except Exception:
            # The transport must never make a task or shutdown fail.
            try:
                self._telemetry_service._record_local_warning("transport_queue_failed")
            except Exception:
                pass
            logger.debug("telemetry envelope queue failed", exc_info=True)

    def _send_request(self, body, headers, endpoint_type, envelope=None):
        if not self._allowed():
            return None
        try:
            return super()._send_request(body, headers, endpoint_type, envelope)
        except Exception:
            try:
                self._telemetry_service._record_local_warning(
                    "transport_request_failed"
                )
            except Exception:
                pass
            logger.debug("telemetry request failed", exc_info=True)
            return None


def _bound_transport_class(service: "TelemetryService", epoch: int):
    """Create a transport class accepted by sentry-sdk's Client factory."""

    class _BoundEpochTransport(EpochBoundHttpTransport):
        _telemetry_service = service
        _telemetry_epoch = epoch

    _BoundEpochTransport.__name__ = "MWUEpochBoundHttpTransport"
    return _BoundEpochTransport


@dataclass
class _TaskHandle:
    run_id: str
    task_name: str
    pi_entry: str
    epoch: int
    span: Span | None = None
    scope: Scope | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished: bool = False


@dataclass
class _NodeHandle:
    run_id: str
    task_name: str | None
    epoch: int
    span: Span | None = None
    scope: Scope | None = None
    started_at: float = field(default_factory=time.monotonic)
    message_type: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    finished: bool = False


@dataclass
class _RunHandle:
    run_id: str
    origin: str
    task_names: list[str]
    epoch: int
    scope: Scope | None = None
    transaction: Transaction | None = None
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


class TelemetryService:
    """Opt-in telemetry backend with an isolated Sentry client."""

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
        self._build_allowed_override = build_allowed
        self._client_factory = client_factory or sentry_sdk.Client
        self._lock = threading.RLock()
        self._client: Any | None = None
        self._transport: Any | None = None
        self._client_epoch: int | None = None
        self._epoch = 0
        self._logs_enabled = False
        self._runs: dict[str, _RunHandle] = {}
        self._saved_sys_excepthook: Any | None = None
        self._saved_threading_excepthook: Any | None = None
        self._saved_loop_handlers: dict[asyncio.AbstractEventLoop, Any] = {}
        self._installed_sys_excepthook: Any | None = None
        self._installed_threading_excepthook: Any | None = None
        self._installed_loop_handlers: dict[asyncio.AbstractEventLoop, Any] = {}
        self._handlers_installed = False
        self._invalid_dsn_reported = False
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
    def client(self) -> Any | None:
        return self._client

    @property
    def transport(self) -> Any | None:
        return self._transport

    @property
    def settings(self) -> SettingsModel:
        return self._settings

    def is_configured(self) -> bool:
        return self._parsed_dsn() is not None

    def is_build_allowed(self) -> bool:
        if self._build_allowed_override is not None:
            return bool(self._build_allowed_override)
        try:
            return bool(runtime_info.telemetry_build_allowed())
        except Exception:
            return False

    def _parsed_dsn(self) -> Dsn | None:
        raw = getattr(getattr(self.interface, "telemetry", None), "sentry", None)
        dsn = getattr(raw, "dsn", None)
        if not isinstance(dsn, str) or not dsn.strip():
            return None
        try:
            return Dsn(dsn.strip())
        except (BadDsn, ValueError, TypeError) as exc:
            if not self._invalid_dsn_reported:
                self._invalid_dsn_reported = True
                logger.warning("telemetry_invalid_dsn: %s", type(exc).__name__)
            return None

    def _normalized_dsn(self, parsed: Dsn | None = None) -> str:
        parsed = parsed or self._parsed_dsn()
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

    def config_id(self) -> str:
        parsed = self._parsed_dsn()
        if parsed is None:
            return ""
        name = str(getattr(self.interface, "name", "")).strip()
        material = name + self._normalized_dsn(parsed)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def recipient(self) -> dict[str, str] | None:
        parsed = self._parsed_dsn()
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
        current_id = self.config_id()
        return (
            consent.consent == "granted"
            and bool(current_id)
            and consent.configId == current_id
            and self.is_build_allowed()
            and self.is_configured()
        )

    def is_active(self) -> bool:
        with self._lock:
            return bool(
                self._authorized()
                and self._client is not None
                and self._client_epoch == self._epoch
            )

    def status_payload(self) -> dict[str, Any]:
        consent = getattr(self._settings, "telemetry", None)
        if not isinstance(consent, TelemetryConsent):
            consent = TelemetryConsent()
        return {
            "configured": self.is_configured(),
            "buildAllowed": self.is_build_allowed(),
            "active": self.is_active(),
            "configId": self.config_id(),
            "recipient": self.recipient(),
            "consent": consent.consent,
            "failureAttachments": bool(consent.failureAttachments),
        }

    def apply_consent(
        self,
        config_id: str,
        consent: Literal["granted", "denied"],
        failure_attachments: bool = False,
    ) -> dict[str, Any]:
        expected = self.config_id()
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
            self.revoke()
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

    def _sentry_options(self, epoch: int, *, experiments: bool) -> dict[str, Any]:
        sentry_config = getattr(
            getattr(self.interface, "telemetry", None), "sentry", None
        )
        tracing = getattr(sentry_config, "tracing", True)
        tracing = True if tracing is None else bool(tracing)
        rate = getattr(sentry_config, "traces_sample_rate", 1.0)
        if rate is None:
            rate = 1.0
        rate = (
            float(rate) if math.isfinite(float(rate)) and 0 <= float(rate) <= 1 else 0.0
        )
        if not tracing:
            rate = 0.0
        project_name = str(getattr(self.interface, "name", "unknown"))
        version = str(getattr(self.interface, "version", None) or "unknown")
        options: dict[str, Any] = {
            "dsn": str(getattr(sentry_config, "dsn", "")).strip(),
            "default_integrations": False,
            "auto_enabling_integrations": False,
            "integrations": [],
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
            "traces_sample_rate": rate,
            "release": f"{project_name}@{version}",
            "environment": "production",
            "before_send": scrub_error_event,
            "before_send_transaction": scrub_transaction_event,
            "transport": _bound_transport_class(self, epoch),
            "debug": False,
        }
        if experiments:
            options["_experiments"] = {
                "trace_lifecycle": "static",
                "enable_logs": True,
                "before_send_log": scrub_log,
            }
        else:
            # The SDK fallback intentionally sends no logs.  Error and
            # transaction callbacks remain installed independently.
            options["enable_logs"] = False
        return options

    def _enable_client(self) -> None:
        if not self._authorized():
            return
        with self._lock:
            old_client = self._client
            self._client = None
            self._transport = None
            self._client_epoch = None
            self._epoch += 1
            epoch = self._epoch
        if old_client is not None:
            self._close_client(old_client, timeout=0)

        client = None
        logs_enabled = False
        try:
            options = self._sentry_options(epoch, experiments=True)
            client = self._client_factory(**options)
            logs_enabled = True
        except TypeError:
            logger.warning("Sentry 实验选项不可用，已禁用结构化 Logs")
            try:
                client = self._client_factory(
                    **self._sentry_options(epoch, experiments=False)
                )
            except Exception:
                logger.warning("Sentry client 初始化失败，遥测保持关闭", exc_info=True)
                client = None
        except Exception:
            logger.warning("Sentry client 初始化失败，遥测保持关闭", exc_info=True)
            client = None

        if client is None:
            return
        with self._lock:
            # A revoke/target change can race client construction.  Do not
            # publish a client into an invalid epoch.
            if not self._authorized() or epoch != self._epoch:
                self._close_client(client, timeout=0)
                return
            self._client = client
            self._transport = getattr(client, "transport", None)
            self._client_epoch = epoch
            self._logs_enabled = logs_enabled
        self._install_exception_handlers()

    @staticmethod
    def _close_client(client: Any, *, timeout: float) -> None:
        try:
            client.close(timeout=timeout)
        except TypeError:
            try:
                client.close()
            except Exception:
                logger.debug("telemetry client close failed", exc_info=True)
        except Exception:
            logger.debug("telemetry client close failed", exc_info=True)

    def revoke(self) -> None:
        """Invalidate the current epoch before closing; never flush old data."""

        with self._lock:
            self._epoch += 1
            old_client = self._client
            self._client = None
            self._client_epoch = None
            self._logs_enabled = False
            self._clear_run_buffers_locked()
        self._restore_exception_handlers()
        if old_client is not None:
            # Client.close() flushes internally in SDK 2.68.1, but the epoch
            # gate makes every queued and in-flight pre-revocation send drop.
            self._close_client(old_client, timeout=0)

    def flush_and_close_limited(self) -> None:
        """Close on normal exit, flushing for at most two seconds if active."""

        with self._lock:
            active = self._authorized() and self._client is not None
            client = self._client
            self._logs_enabled = False
            self._clear_run_buffers_locked()
        self._restore_exception_handlers()
        if client is not None:
            # Keep the client/epoch visible to the transport while Client.close
            # drains its queue.  Unlike revoke(), normal shutdown is allowed a
            # bounded flush; invalidate the epoch only after close returns.
            self._close_client(client, timeout=2.0 if active else 0)
        with self._lock:
            if self._client is client:
                self._epoch += 1
                self._client = None
                self._transport = None
                self._client_epoch = None

    shutdown = flush_and_close_limited

    def _can_send_epoch(self, epoch: int) -> bool:
        with self._lock:
            return bool(
                epoch == self._epoch
                and self._client is not None
                and self._client_epoch == epoch
                and self._authorized()
            )

    def _install_exception_handlers(self) -> None:
        with self._lock:
            if self._handlers_installed or not self.is_active():
                return
            self._saved_sys_excepthook = sys.excepthook
            self._installed_sys_excepthook = self._sys_excepthook
            sys.excepthook = self._installed_sys_excepthook
            if hasattr(threading, "excepthook"):
                self._saved_threading_excepthook = threading.excepthook
                self._installed_threading_excepthook = self._threading_excepthook
                threading.excepthook = self._installed_threading_excepthook
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                self._saved_loop_handlers[loop] = loop.get_exception_handler()
                installed = self._loop_exception_handler
                self._installed_loop_handlers[loop] = installed
                loop.set_exception_handler(installed)
            self._handlers_installed = True

    def _restore_exception_handlers(self) -> None:
        with self._lock:
            if not self._handlers_installed:
                return
            if (
                self._saved_sys_excepthook is not None
                and sys.excepthook is self._installed_sys_excepthook
            ):
                sys.excepthook = self._saved_sys_excepthook
            if (
                self._saved_threading_excepthook is not None
                and getattr(threading, "excepthook", None)
                is self._installed_threading_excepthook
            ):
                threading.excepthook = self._saved_threading_excepthook
            for loop, handler in list(self._saved_loop_handlers.items()):
                try:
                    if (
                        not loop.is_closed()
                        and loop.get_exception_handler()
                        is self._installed_loop_handlers.get(loop)
                    ):
                        loop.set_exception_handler(handler)
                except Exception:
                    pass
            self._saved_loop_handlers.clear()
            self._installed_loop_handlers.clear()
            self._saved_sys_excepthook = None
            self._saved_threading_excepthook = None
            self._installed_sys_excepthook = None
            self._installed_threading_excepthook = None
            self._handlers_installed = False

    def _sys_excepthook(self, exc_type, exc_value, exc_traceback) -> None:
        try:
            if isinstance(exc_value, BaseException):
                self.capture_exception(
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
                self.capture_exception(
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
                self.capture_exception(value, error_code="unhandled_exception")
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
            safe_attrs: dict[str, Any] = {"event_name": event_name}
            for key, value in attrs.items():
                safe = _safe_attribute(key, value)
                if safe is not None:
                    safe_attrs[key] = safe
        if not self._can_send_epoch(epoch):
            return
        log = {
            "severity_text": severity
            if severity in {"debug", "info", "warning", "error", "fatal"}
            else "info",
            "severity_number": {
                "debug": 5,
                "info": 9,
                "warning": 13,
                "error": 17,
                "fatal": 21,
            }.get(severity, 9),
            "body": event_name,
            "attributes": safe_attrs,
            "time_unix_nano": time.time_ns(),
            "trace_id": None,
            "span_id": None,
        }
        try:
            scope = Scope(client=client)
            capture = getattr(client, "_capture_log", None)
            if capture is not None:
                capture(log, scope=scope)
        except Exception:
            self._record_local_warning("log_capture_failed")

    def _new_scope(self, client: Any) -> Scope:
        scope = Scope(client=client)
        for key, value in self._common_tags.items():
            scope.set_tag(key, value)
        return scope

    @staticmethod
    def _start_child(parent: Transaction | Span, *, op: str, name: str) -> Span:
        """Start a child without consulting sentry_sdk's global client/hub."""

        child = Span(
            trace_id=parent.trace_id,
            parent_span_id=parent.span_id,
            sampled=parent.sampled,
            containing_transaction=parent.containing_transaction or parent,
            op=op,
            name=name,
            origin="manual",
        )
        recorder = getattr(
            parent.containing_transaction or parent, "_span_recorder", None
        )
        if recorder is not None:
            recorder.add(child)
        return child

    def start_run(
        self,
        run_id: str,
        origin: str,
        task_names: list[str] | None = None,
    ) -> _RunHandle | None:
        if not self.is_active():
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
            client = self._client
        scope = self._new_scope(client)
        transaction: Transaction | None = None
        sentry_config = getattr(
            getattr(self.interface, "telemetry", None), "sentry", None
        )
        tracing = getattr(sentry_config, "tracing", True)
        if tracing is None:
            tracing = True
        rate = getattr(sentry_config, "traces_sample_rate", 1.0)
        if bool(tracing) and (rate is None or float(rate) > 0):
            try:
                # Build the transaction directly instead of calling
                # Scope.start_transaction: SDK sampling helpers eventually
                # consult the process-global client, which may belong to the
                # embedded Agent.  The explicit Bernoulli decision has the
                # same traces_sample_rate contract and remains isolated.
                rate = max(0.0, min(float(rate), 1.0))
                sampled = rate >= 1.0 or random.random() < rate
                transaction = Transaction(
                    name="mwu.run",
                    op="mwu.run",
                    sampled=sampled,
                    scope=scope,
                    origin="manual",
                )
                transaction.sample_rate = rate
                if sampled:
                    transaction.init_span_recorder(maxlen=1000)
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
            scope=scope,
            transaction=transaction,
        )
        with self._lock:
            if not self._can_send_epoch(epoch):
                return None
            self._runs[run_id] = handle
        if bool(tracing):
            self._capture_log(
                "mwu.run.started",
                {
                    "run_id": run_id,
                    "origin": origin,
                    "task_name": task_names[0] if task_names else None,
                },
            )
        return handle

    def finish_run(self, run_id: str, result: str) -> None:
        with self._lock:
            handle = self._runs.pop(run_id, None)
            client = self._client
        if handle is None:
            return
        result = result if result in _ALLOWED_RESULTS else "failed"
        sentry_result = {
            "success": "ok",
            "failed": "internal_error",
            "stopped": "cancelled",
        }.get(result, result)
        sentry_config = getattr(
            getattr(self.interface, "telemetry", None), "sentry", None
        )
        tracing = getattr(sentry_config, "tracing", True)
        if tracing is None:
            tracing = True
        duration_ms = int(max(0.0, time.monotonic() - handle.started_at) * 1000)
        if handle.transaction is not None:
            try:
                handle.transaction.set_data("result", sentry_result)
                handle.transaction.set_data("duration_ms", duration_ms)
                handle.transaction.set_status(sentry_result)
                if self._can_send_epoch(handle.epoch):
                    self._finish_transaction(handle, client=client)
            except Exception:
                logger.debug("telemetry run transaction finish failed", exc_info=True)
        if bool(tracing):
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

    def _finish_transaction(self, handle: _RunHandle, *, client: Any | None) -> None:
        """Serialize and capture a transaction without touching the global hub.

        ``Transaction.finish()`` in sentry-sdk 2.68.1 resolves the global
        ``sentry_sdk.get_client()``.  That is unsafe for MWU's embedded Agent,
        so the small equivalent below sends through this service's client.
        """

        transaction = handle.transaction
        scope = handle.scope
        if transaction is None or client is None or scope is None:
            return
        if transaction.timestamp is not None:
            return
        if transaction.sampled is False:
            return
        transaction.timestamp = datetime.now().astimezone()
        event = transaction.to_json()
        event["type"] = "transaction"
        event["transaction"] = transaction.name
        event["start_timestamp"] = transaction.start_timestamp
        event["timestamp"] = transaction.timestamp
        event["release"] = _client_option(client, "release")
        event["environment"] = _client_option(client, "environment")
        event["tags"] = dict(self._common_tags)
        event["contexts"] = {
            "trace": {
                "trace_id": transaction.trace_id,
                "span_id": transaction.span_id,
            }
        }
        recorder = getattr(transaction, "_span_recorder", None)
        if recorder is not None:
            spans: list[dict[str, Any]] = []
            for span in recorder.spans:
                if span is transaction or span.timestamp is None:
                    continue
                spans.append(span.to_json())
            if spans:
                event["spans"] = spans
        client.capture_event(event, hint={}, scope=scope)

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
                run.controller_type = _safe_identifier(controller_type, max_length=64)
            if resource_name is not None:
                run.resource_name = _safe_identifier(resource_name, max_length=256)

    def start_task(
        self, run_id: str, task_name: str, pi_entry: str
    ) -> _TaskHandle | None:
        if not self.is_active():
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
                scope=run.scope,
            )
            if run.transaction is not None:
                try:
                    task.span = self._start_child(
                        run.transaction, op="maa.task", name="maa.task"
                    )
                    task.span.set_data("task_name", task.task_name)
                    task.span.set_data("pi_entry", task.pi_entry)
                except Exception:
                    logger.debug("telemetry task span failed", exc_info=True)
            run.tasks[task.task_name] = task
            return task

    def finish_task(
        self, handle: _TaskHandle | None, status: str, error_code: str | None = None
    ) -> None:
        if handle is None or handle.finished:
            return
        handle.finished = True
        status = status if status in _ALLOWED_RESULTS else "failed"
        duration_ms = int(max(0.0, time.monotonic() - handle.started_at) * 1000)
        if handle.span is not None:
            try:
                handle.span.set_data("task_name", handle.task_name)
                handle.span.set_data("result", status)
                handle.span.set_data("duration_ms", duration_ms)
                if error_code:
                    handle.span.set_data("error_code", _safe_code(error_code))
                handle.span.set_status(
                    {
                        "success": "ok",
                        "failed": "internal_error",
                        "stopped": "cancelled",
                    }.get(status, status)
                )
                handle.span.finish(scope=handle.scope)
            except Exception:
                logger.debug("telemetry task span finish failed", exc_info=True)
        sentry_config = getattr(
            getattr(self.interface, "telemetry", None), "sentry", None
        )
        tracing = getattr(sentry_config, "tracing", True)
        if tracing is None:
            tracing = True
        if bool(tracing):
            self._capture_log(
                "mwu.task.finished",
                {
                    "run_id": handle.run_id,
                    "task_name": handle.task_name,
                    "pi_entry": handle.pi_entry,
                    "controller_type": self._run_context_value(
                        handle.run_id, "controller_type"
                    ),
                    "resource_name": self._run_context_value(
                        handle.run_id, "resource_name"
                    ),
                    "result": status,
                    "duration_ms": duration_ms,
                    "error_code": error_code,
                },
                severity="error" if status == "failed" else "info",
            )
        with self._lock:
            run = self._runs.get(handle.run_id)
            if run is not None:
                run.tasks.pop(handle.task_name, None)

    def _run_context_value(self, run_id: str, key: str) -> str | None:
        with self._lock:
            run = self._runs.get(run_id)
            return getattr(run, key, None) if run is not None else None

    def node_span(
        self,
        run_id: str,
        task_name: str | None = None,
        message_type: str | None = None,
        details: dict[str, Any] | None = None,
        trace_allowed: bool = False,
    ) -> _NodeHandle | None:
        sentry_config = getattr(
            getattr(self.interface, "telemetry", None), "sentry", None
        )
        tracing = getattr(sentry_config, "tracing", True)
        if tracing is None:
            tracing = True
        if not trace_allowed or not bool(tracing) or not self.is_active():
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
                    span = self._start_child(parent, op="maa.node", name="maa.node")
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
                scope=run.scope,
                message_type=message_type,
                attributes=attrs,
            )
            if span is not None:
                for key, value in attrs.items():
                    safe = _safe_attribute(key, value)
                    if safe is not None:
                        span.set_data(key, safe)
            return node

    def finish_node_span(
        self, handle: _NodeHandle | None, result: str | None = None
    ) -> None:
        if handle is None or handle.finished:
            return
        handle.finished = True
        result = result or "success"
        if result not in _ALLOWED_RESULTS:
            result = "failed" if str(result).endswith("Failed") else "success"
        duration_ms = int(max(0.0, time.monotonic() - handle.started_at) * 1000)
        if handle.span is not None:
            try:
                handle.span.set_data("result", result)
                handle.span.set_data("duration_ms", duration_ms)
                handle.span.set_status("internal_error" if result == "failed" else "ok")
                handle.span.finish(scope=handle.scope)
            except Exception:
                logger.debug("telemetry node span finish failed", exc_info=True)
        sentry_config = getattr(
            getattr(self.interface, "telemetry", None), "sentry", None
        )
        tracing = getattr(sentry_config, "tracing", True)
        if tracing is None:
            tracing = True
        if bool(tracing):
            self._capture_log(
                "mwu.node.result",
                {
                    **handle.attributes,
                    "result": result,
                    "duration_ms": duration_ms,
                },
                severity="error" if result == "failed" else "info",
            )
        self.record_diagnostic(
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

    def record_diagnostic(
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
            record: dict[str, Any] = {"time": int(time.time())}
            for key, value in {
                "message_type": message_type,
                "task_name": task_name,
                "result": result,
                **attrs,
            }.items():
                safe = _safe_attribute(key, value)
                if safe is not None:
                    record[key] = safe
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
        try:
            image = getattr(controller, "cached_image", None)
        except Exception:
            return None
        if image is None:
            return None
        try:
            if isinstance(image, Image.Image):
                return image.copy()
            copier = getattr(image, "copy", None)
            if callable(copier):
                return copier()
            return image
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
            consent = self._settings.telemetry
            if not consent.failureAttachments:
                return []
            sentry_config = getattr(
                getattr(self.interface, "telemetry", None), "sentry", None
            )
            rate = getattr(sentry_config, "failure_attachments_sample_rate", 1.0)
            if rate is None:
                rate = 1.0
            try:
                rate = float(rate)
            except (TypeError, ValueError):
                return []
            if not math.isfinite(rate) or rate <= 0 or random.random() >= rate:
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
        if not self.is_active():
            return
        error_code = _safe_code(error_code)
        run: _RunHandle | None = None
        with self._lock:
            if run_id is not None:
                run = self._runs.get(run_id)
                if run is not None and error_code in run.errors:
                    return
                if run is not None:
                    run.errors.add(error_code)
            client = self._client
            epoch = self._client_epoch
        if client is None or epoch is None or not self._can_send_epoch(epoch):
            return
        if exception is None:
            exception = RuntimeError(error_code)
        event: dict[str, Any] = {
            "exception": {
                "values": [
                    {
                        "type": type(exception).__name__,
                        # Never place the exception text in the event object;
                        # before_send is a second defense, not the first.
                        "value": _safe_code(error_code),
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": frame.name,
                                    "lineno": frame.lineno,
                                }
                                for frame in traceback_module.extract_tb(
                                    traceback or exception.__traceback__
                                )
                            ]
                        },
                    }
                ]
            },
            "tags": self._common_tags,
            "release": _client_option(client, "release"),
            "environment": _client_option(client, "environment"),
            "contexts": {
                "mwu": {
                    "run_id": run_id,
                    "task_name": task_name,
                    "error_code": error_code,
                }
            },
        }
        attachments = (
            self._failure_attachments(run, controller=controller)
            if attach and run is not None
            else []
        )
        scope = self._new_scope(client)
        for filename, payload, content_type in attachments:
            scope.add_attachment(
                bytes=payload,
                filename=filename,
                content_type=content_type,
                add_to_transactions=False,
            )
        hint = {"telemetry_error_code": error_code}
        if exception is not None:
            hint["exc_info"] = (
                type(exception),
                exception,
                traceback or exception.__traceback__,
            )
        try:
            client.capture_event(event, hint=hint, scope=scope)
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
        except Exception:
            self._record_local_warning("error_capture_failed")

    def capture_exception(
        self,
        exception: BaseException,
        *,
        run_id: str | None = None,
        error_code: str = "mwu.error",
        traceback: TracebackType | None = None,
        task_name: str | None = None,
    ) -> None:
        self._capture_error(
            run_id,
            error_code=error_code,
            exception=exception,
            traceback=traceback,
            task_name=task_name,
        )

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

    def capture_task_failed(
        self,
        run_id: str,
        task_name: str,
        exception: BaseException | None = None,
        *,
        controller: Any | None = None,
        status: str | None = None,
    ) -> None:
        if status in {"stopped", "cancelled"}:
            return
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
    "EpochBoundHttpTransport",
    "TelemetryConsentStaleError",
    "TelemetryService",
    "scrub_error_event",
    "scrub_log",
    "scrub_transaction_event",
]
