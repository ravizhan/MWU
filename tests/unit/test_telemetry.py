from pathlib import Path, PureWindowsPath
from typing import Any

import pytest

from models.interface import InterfaceModel
from services import telemetry


def _interface(**extra) -> InterfaceModel:
    return InterfaceModel.model_validate(
        {
            "interface_version": 2,
            "name": "Test",
            "controller": [{"name": "ADB", "label": "ADB", "type": "Adb"}],
            "resource": [{"name": "res", "path": []}],
            "task": [],
            **extra,
        }
    )


def test_before_send_scrubs_paths_and_host(monkeypatch):
    monkeypatch.setattr(telemetry, "_app_root", PureWindowsPath("D:/X/MWU"))
    monkeypatch.setattr(Path, "home", lambda: PureWindowsPath("D:/X"))
    event: Any = {
        "server_name": "host",
        "exception": {
            "values": [{"value": "open D:\\X\\MWU\\config\\settings.json failed"}]
        },
        "message": "user file d:/x/notes.txt",
        "contexts": {"device": {"name": "my-pc", "arch": "x64"}},
    }

    result = telemetry._before_send(event, {})

    assert "server_name" not in result
    assert result["contexts"]["device"] == {"arch": "x64"}
    assert result["exception"]["values"][0]["value"] == (
        "open <app>\\config\\settings.json failed"
    )
    assert result["message"] == "user file <home>/notes.txt"


def test_summarize_options_hides_secrets():
    interface = _interface(
        option={
            "mode": {"cases": [{"name": "a"}, {"name": "b"}]},
            "items": {"type": "checkbox", "cases": [{"name": "x"}, {"name": "y"}]},
            "account": {
                "type": "input",
                "inputs": [
                    {"name": "password", "password": True},
                    {"name": "count", "pipeline_type": "int"},
                    {"name": "nickname"},
                ],
            },
            "_hidden": {"cases": [{"name": "a"}]},
        }
    )

    summary = telemetry.summarize_options(
        {
            "mode": "b",
            "items": ["y", "x"],
            "account": {"password": "secret", "count": "3", "nickname": "me"},
            "_hidden": "a",
            "unknown": "z",
        },
        interface,
    )

    assert summary == {
        "mode": "b",
        "items": "x,y",
        "account": {"count": "3", "nickname": "filled"},
    }


@pytest.mark.parametrize(
    ("extra", "force", "expected"),
    [
        ({}, False, "no_dsn"),
        ({"telemetry": {"sentry": {"dsn": "  "}}}, True, "no_dsn"),
        ({"telemetry": {"sentry": {"dsn": "http://k@h/1"}}}, False, "dev_build"),
        (
            {"telemetry": {"sentry": {"dsn": "http://k@h/1"}}, "version": "v1"},
            True,
            None,
        ),
    ],
)
def test_configure_gate(tmp_path, monkeypatch, extra, force, expected):
    if force:
        monkeypatch.setenv("MWU_TELEMETRY_FORCE", "1")
    else:
        monkeypatch.delenv("MWU_TELEMETRY_FORCE", raising=False)

    telemetry.configure(_interface(**extra), tmp_path)

    assert telemetry.status() == {
        "available": expected is None,
        "blocked_reason": expected,
        "enabled": False,
    }
