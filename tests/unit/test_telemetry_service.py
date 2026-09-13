from pathlib import Path

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from models.interface import InterfaceModel
from models.settings import SettingsModel, TelemetryConsent
from services.telemetry_service import (
    TelemetryConsentStaleError,
    TelemetryService,
    task_span,
)

_created_services: list[TelemetryService] = []


@pytest.fixture(autouse=True)
def _cleanup_services():
    yield
    for service in _created_services:
        service._revoke()
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
    service = TelemetryService(
        _interface(**{"dsn": "https://public@example.test/42", **sentry}),
        SettingsModel(),
        tmp_path / "settings.json",
        build_allowed=True,
    )
    _created_services.append(service)
    return service


def test_config_id_is_stable_and_dsn_change_is_stale(tmp_path):
    first = _service(tmp_path)
    config_id = first._config_id
    assert config_id == _service(tmp_path)._config_id
    first.apply_consent(config_id, "granted")
    assert first.status_payload()["active"] is True

    changed = _service(tmp_path, dsn="https://public@example.test/43")
    assert changed._config_id != config_id
    with pytest.raises(TelemetryConsentStaleError):
        changed.apply_consent(config_id, "granted")


def test_missing_or_blank_dsn_keeps_telemetry_disabled(tmp_path):
    for index, sentry in enumerate(({}, {"dsn": "   "})):
        service = TelemetryService(
            _interface(**sentry),
            SettingsModel(),
            tmp_path / f"settings-{index}.json",
            build_allowed=True,
        )
        _created_services.append(service)

        assert service._client is None
        status = service.status_payload()
        assert status["configured"] is False
        assert status["active"] is False
        assert status["consent"] == "unknown"
        assert status["failureAttachments"] is False


def test_status_projects_stale_disk_consent_to_unknown(tmp_path):
    previous_target = _service(tmp_path)._config_id
    settings = SettingsModel(
        telemetry=TelemetryConsent(
            consent="granted",
            configId=previous_target,
            failureAttachments=True,
        )
    )
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(settings.model_dump_json(), encoding="utf-8")
    persisted = settings_path.read_bytes()
    service = TelemetryService(
        _interface(dsn="https://public@example.test/43"),
        settings_path=settings_path,
        build_allowed=True,
    )
    _created_services.append(service)

    status = service.status_payload()

    assert status["configured"] is True
    assert status["configId"] != previous_target
    assert status["consent"] == "unknown"
    assert status["failureAttachments"] is False
    assert service.settings.telemetry.consent == "granted"
    assert service.settings.telemetry.configId == previous_target
    assert service.settings.telemetry.failureAttachments is True
    assert settings_path.read_bytes() == persisted


def test_recipient_does_not_expose_dsn_key(tmp_path):
    service = _service(tmp_path, dsn="https://public-secret@example.test/path/42")
    recipient = service.status_payload()["recipient"]
    assert recipient == {
        "project": "Telemetry Game",
        "host": "example.test",
        "path": "/path",
        "project_id": "42",
    }
    assert "public-secret" not in repr(recipient)


def test_tracing_false_suppresses_lifecycle_logs_and_spans(tmp_path):
    service = _service(tmp_path, tracing=False)
    service.apply_consent(service._config_id, "granted")
    run = service.start_run("run-1", "manual", ["Task"])
    assert run is not None
    assert run.transaction is None
    with task_span(service, "run-1", "Task", "Entry") as task:
        assert task.span is None
    service.finish_run("run-1", "success")


def test_epoch_revocation_drops_future_captures(tmp_path):
    received: list[object] = []

    class _Recorder(Transport):
        def capture_envelope(self, envelope):
            received.append(envelope)

    def factory(**options):
        options["transport"] = _Recorder()
        return sentry_sdk.Client(**options)

    service = TelemetryService(
        _interface(dsn="https://public@example.test/42"),
        SettingsModel(),
        tmp_path / "settings.json",
        build_allowed=True,
        client_factory=factory,
    )
    _created_services.append(service)
    service.apply_consent(service._config_id, "granted")
    epoch = service._client_epoch
    assert epoch is not None

    service.capture_task_failed("run-1", "Task", RuntimeError("secret"))
    service._client.flush(timeout=2.0)
    # An error report fans out over two channels: the error event itself and
    # the matching structured log.
    delivered = len(received)
    assert delivered >= 1

    service._revoke()

    assert not service._can_send_epoch(epoch)
    assert service.status_payload()["active"] is False
    assert service._client is None
    service.capture_task_failed("run-1", "Task", RuntimeError("secret"))
    assert len(received) == delivered


def test_consent_installs_and_revocation_detaches_the_global_client(tmp_path):
    service = _service(tmp_path)
    service.apply_consent(service._config_id, "granted")
    client = service._client
    assert client is not None
    assert sentry_sdk.get_global_scope().client is client

    service.apply_consent(service._config_id, "denied")

    assert service._client is None
    assert sentry_sdk.get_global_scope().client is not client


def test_agent_installed_client_is_never_clobbered(tmp_path):
    """An embedded Agent may take the global slot; MWU must yield, not fight."""

    service = _service(tmp_path)
    service.apply_consent(service._config_id, "granted")

    sentry_sdk.init(
        dsn="https://public@example.test/99",
        default_integrations=False,
        integrations=[],
    )
    agent_client = sentry_sdk.get_global_scope().client
    try:
        # MWU cannot deliver through a client it no longer owns, and must say so
        # instead of reporting an active telemetry path that cannot send.
        assert service.status_payload()["active"] is False

        service.apply_consent(service._config_id, "denied")

        assert sentry_sdk.get_global_scope().client is agent_client
    finally:
        sentry_sdk.get_global_scope().set_client(None)
