import importlib
import sys
from types import SimpleNamespace

import pytest

from models.interface import InterfaceModel
from services.telemetry_service import TelemetryConsentStaleError


@pytest.fixture
def isolated_main(monkeypatch, tmp_path):
    sys.modules.pop("main", None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "mwu.exe"))
    (tmp_path / "page" / "assets").mkdir(parents=True)
    (tmp_path / "resource").mkdir()

    interface = InterfaceModel.model_validate(
        {
            "interface_version": 2,
            "name": "Test",
            "controller": [{"name": "ADB", "label": "ADB", "type": "Adb"}],
            "resource": [{"name": "main", "path": ["resource"]}],
            "task": [],
        }
    )
    monkeypatch.setattr(
        "models.interface_loader.load_interface_model",
        lambda _app_root: interface,
    )

    module = importlib.import_module("main")
    try:
        yield module
    finally:
        sys.modules.pop("main", None)


class _FakeTelemetry:
    def __init__(self):
        self.settings = SimpleNamespace(telemetry="updated")
        self.calls = []

    def status_payload(self):
        return {
            "configured": True,
            "buildAllowed": True,
            "active": False,
            "configId": "current",
            "recipient": {
                "project": "Game",
                "host": "example.test",
                "project_id": "42",
            },
            "consent": "unknown",
            "failureAttachments": False,
        }

    def apply_consent(self, config_id, consent, failure_attachments):
        self.calls.append((config_id, consent, failure_attachments))
        if config_id != "current":
            raise TelemetryConsentStaleError("stale")
        return self.status_payload() | {
            "consent": consent,
            "failureAttachments": failure_attachments
            if consent == "granted"
            else False,
        }


def test_get_telemetry_without_service_is_safe(isolated_main, monkeypatch):
    monkeypatch.setattr(isolated_main.app_state, "telemetry_service", None)
    payload = isolated_main.get_telemetry()
    assert payload["status"] == "success"
    assert payload["consent"] == "unknown"
    assert payload["active"] is False


def test_consent_api_rejects_stale_target(isolated_main, monkeypatch):
    fake = _FakeTelemetry()
    monkeypatch.setattr(isolated_main.app_state, "telemetry_service", fake)
    response = isolated_main.set_telemetry_consent(
        isolated_main.TelemetryConsentRequest(
            configId="old",
            consent="granted",
            failureAttachments=True,
        )
    )
    assert response.status_code == 409
    assert fake.calls == [("old", "granted", True)]


def test_consent_api_write_failure_returns_error(isolated_main, monkeypatch):
    class _Failing(_FakeTelemetry):
        def apply_consent(self, config_id, consent, failure_attachments):
            raise OSError("disk full")

    fake = _Failing()
    monkeypatch.setattr(isolated_main.app_state, "telemetry_service", fake)
    response = isolated_main.set_telemetry_consent(
        isolated_main.TelemetryConsentRequest(configId="current", consent="granted")
    )
    assert response.status_code == 500
    assert response.body and b"disk full" in response.body
