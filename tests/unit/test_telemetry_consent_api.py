from types import SimpleNamespace

import main
from main import TelemetryConsentRequest, get_telemetry, set_telemetry_consent
from services.telemetry_service import TelemetryConsentStaleError


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


def test_get_telemetry_without_service_is_safe(monkeypatch):
    monkeypatch.setattr(main.app_state, "telemetry_service", None)
    payload = get_telemetry()
    assert payload["status"] == "success"
    assert payload["consent"] == "unknown"
    assert payload["active"] is False


def test_consent_api_rejects_stale_target(monkeypatch):
    fake = _FakeTelemetry()
    monkeypatch.setattr(main.app_state, "telemetry_service", fake)
    response = set_telemetry_consent(
        TelemetryConsentRequest(
            configId="old",
            consent="granted",
            failureAttachments=True,
        )
    )
    assert response.status_code == 409
    assert fake.calls == [("old", "granted", True)]


def test_consent_api_write_failure_returns_error(monkeypatch):
    class _Failing(_FakeTelemetry):
        def apply_consent(self, *args):
            raise OSError("disk full")

    fake = _Failing()
    monkeypatch.setattr(main.app_state, "telemetry_service", fake)
    response = set_telemetry_consent(
        TelemetryConsentRequest(configId="current", consent="granted")
    )
    assert response.status_code == 500
    assert response.body and b"disk full" in response.body
