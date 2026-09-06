from pathlib import Path
from typing import ClassVar

import pytest

from models.interface import InterfaceModel
from models.settings import SettingsModel, TelemetryConsent
from services.telemetry_service import (
    TelemetryConsentStaleError,
    TelemetryService,
    scrub_error_event,
    scrub_log,
    scrub_transaction_event,
)


class _FakeClient:
    instances: ClassVar[list["_FakeClient"]] = []

    def __init__(self, **options):
        self.options = options
        self.events: list[dict] = []
        self.logs: list[dict] = []
        self.attachments: list[list[str]] = []
        self.closed: list[float | None] = []
        self.__class__.instances.append(self)

    def capture_event(self, event, hint=None, scope=None):
        callback = self.options.get(
            "before_send_transaction"
            if event.get("type") == "transaction"
            else "before_send"
        )
        scrubbed = callback(event, hint or {}) if callback else event
        if scrubbed is not None:
            self.events.append(scrubbed)
            self.attachments.append(
                [item.filename for item in getattr(scope, "_attachments", [])]
                if scope is not None
                else []
            )
        return "event-id"

    def _capture_log(self, log, scope=None):
        callback = self.options.get("_experiments", {}).get("before_send_log")
        scrubbed = callback(log, {}) if callback else None
        if scrubbed is not None:
            self.logs.append(scrubbed)

    def close(self, timeout=None):
        self.closed.append(timeout)


_created_services: list[TelemetryService] = []


@pytest.fixture(autouse=True)
def _cleanup_services():
    yield
    for service in _created_services:
        service.revoke()
    _created_services.clear()


def _interface(**sentry):
    return InterfaceModel.model_validate(
        {
            "interface_version": 2,
            "name": "Telemetry Game",
            "version": "1.0",
            "controller": [],
            "resource": [],
            "telemetry": {"sentry": sentry},
        }
    )


def _service(tmp_path: Path, **sentry) -> TelemetryService:
    _FakeClient.instances.clear()
    service = TelemetryService(
        _interface(**{"dsn": "https://public@example.test/42", **sentry}),
        SettingsModel(),
        tmp_path / "settings.json",
        build_allowed=True,
        client_factory=_FakeClient,
    )
    _created_services.append(service)
    return service


def test_config_id_is_stable_and_dsn_change_is_stale(tmp_path):
    first = _service(tmp_path)
    config_id = first.config_id()
    assert config_id == _service(tmp_path).config_id()
    first.apply_consent(config_id, "granted")
    assert first.is_active()

    changed = _service(tmp_path, dsn="https://public@example.test/43")
    assert changed.config_id() != config_id
    with pytest.raises(TelemetryConsentStaleError):
        changed.apply_consent(config_id, "granted")


def test_recipient_does_not_expose_dsn_key(tmp_path):
    service = _service(tmp_path, dsn="https://public-secret@example.test/path/42")
    recipient = service.recipient()
    assert recipient == {
        "project": "Telemetry Game",
        "host": "example.test",
        "path": "/path",
        "project_id": "42",
    }
    assert "public-secret" not in repr(recipient)


def test_scrubbers_are_whitelist_only():
    error = scrub_error_event(
        {
            "exception": {
                "values": [
                    {
                        "type": "ValueError",
                        "value": "SECRET exception value",
                        "stacktrace": {
                            "frames": [
                                {
                                    "filename": "C:/SECRET/project.py",
                                    "function": "C:/SECRET/function",
                                    "lineno": 9,
                                }
                            ]
                        },
                    }
                ]
            },
            "request": {"headers": {"Authorization": "SECRET"}},
            "locals": {"secret": "SECRET"},
            "extra": {"secret": "SECRET"},
        },
        {"telemetry_error_code": "mwu.task.failed"},
    )
    encoded = repr(error)
    assert "SECRET" not in encoded
    encoded = repr(
        scrub_error_event(
            {
                "event_id": "SECRET",
                "platform": "SECRET",
                "release": "SECRET",
                "environment": "SECRET",
                "exception": {"values": [{"value": "SECRET"}]},
            }
        )
    )
    assert "SECRET" not in encoded
    assert error["exception"]["values"][0]["type"] == "ValueError"
    assert error["exception"]["values"][0]["stacktrace"]["frames"] == [
        {"function": "function", "lineno": 9}
    ]

    log = scrub_log(
        {
            "body": "mwu.run.started",
            "attributes": {
                "event_name": "mwu.run.started",
                "run_id": "run-1",
                "options": "SECRET",
                "body": "SECRET",
            },
            "time_unix_nano": "SECRET",
            "trace_id": "SECRET",
        }
    )
    assert log is not None
    assert "SECRET" not in repr(log)
    assert set(log["attributes"]) == {"event_name", "run_id"}

    transaction = scrub_transaction_event(
        {
            "type": "transaction",
            "transaction": "mwu.run",
            "extra": {"secret": "SECRET"},
            "spans": [
                {"op": "maa.task", "data": {"task_name": "Task", "secret": "SECRET"}}
            ],
        }
    )
    assert "SECRET" not in repr(transaction)
    assert transaction["spans"][0]["data"] == {"task_name": "Task"}


def test_tracing_false_suppresses_lifecycle_logs_and_spans(tmp_path):
    service = _service(tmp_path, tracing=False)
    service.apply_consent(service.config_id(), "granted")
    run = service.start_run("run-1", "manual", ["Task"])
    assert run is not None
    assert run.transaction is None
    task = service.start_task("run-1", "Task", "Entry")
    assert task is not None
    service.finish_task(task, "success")
    assert _FakeClient.instances[-1].logs == []
    service.finish_run("run-1", "success")


def test_attachment_rate_zero_and_stopped_never_capture_attachment_or_error(tmp_path):
    service = _service(tmp_path, failure_attachments_sample_rate=0)
    service.apply_consent(service.config_id(), "granted", True)
    service.start_run("run-1", "manual", ["Task"])

    class _Controller:
        @property
        def cached_image(self):
            raise AssertionError("rate zero must not inspect cached_image")

    service.capture_task_failed("run-1", "Task", controller=_Controller())
    assert len(_FakeClient.instances[-1].events) == 1
    assert _FakeClient.instances[-1].attachments == [[]]
    service.capture_task_failed("run-1", "Task", status="stopped")
    assert len(_FakeClient.instances[-1].events) == 1


def test_epoch_revocation_drops_future_captures(tmp_path):
    service = _service(tmp_path)
    service.apply_consent(service.config_id(), "granted")
    client = service.client
    assert client is not None
    epoch = service._client_epoch
    assert epoch is not None
    service.revoke()
    assert not service._can_send_epoch(epoch)
    service.capture_exception(RuntimeError("secret"))
    assert client.events == []
