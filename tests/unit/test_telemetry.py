import sys
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest

from maa_worker.focus_protocol import UnifiedFocusResolver
from models.interface import InterfaceModel, SentryTelemetry
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


def test_consent_initializes_without_optional_integrations(tmp_path, monkeypatch):
    # Nuitka 打包产物只包含实际导入的 sentry 集成，自动启用集成的模块不存在
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.aiohttp", None)
    monkeypatch.setenv("MWU_TELEMETRY_FORCE", "1")
    telemetry.configure(
        _interface(
            telemetry={"sentry": {"dsn": "http://k@127.0.0.1:9/1"}}, version="v1"
        ),
        tmp_path,
    )

    telemetry.apply_consent(True)
    try:
        assert telemetry.status()["enabled"] is True
    finally:
        telemetry.shutdown()


@pytest.mark.parametrize(
    ("msg", "focus", "expected"),
    [
        ("Node.PipelineNode.Failed", None, True),
        ("Node.PipelineNode.Succeeded", None, False),
        ("Node.PipelineNode.Succeeded", {"trace": True}, True),
        ("Node.PipelineNode.Failed", {"content": "x", "trace": False}, False),
    ],
)
def test_effective_trace(msg, focus, expected):
    details = {"focus": {msg: focus}} if focus is not None else {}
    assert UnifiedFocusResolver.effective_trace(msg, details) is expected


def test_trace_node_records_only_during_active_run(monkeypatch):
    monkeypatch.setattr(telemetry, "_initialized", True)
    monkeypatch.setattr(telemetry, "_config", SentryTelemetry(dsn="x"))
    monkeypatch.setattr(telemetry, "_current_run", None)
    details = {"name": "Node", "task_id": 7, "focus": {"secret": "x"}}

    telemetry.trace_node("Node.PipelineNode.Failed", details)
    run = telemetry.start_run("manual")
    assert run is not None
    telemetry.trace_node("Node.PipelineNode.Failed", details)

    assert [{k: v for k, v in node.items() if k != "at"} for node in run._nodes] == [
        {"msg": "Node.PipelineNode.Failed", "name": "Node", "task_id": "7"}
    ]
