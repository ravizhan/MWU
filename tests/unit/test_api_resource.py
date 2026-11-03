import importlib
import sys

import pytest

from backend.models.interface import InterfaceModel

_RELOADED = ("backend.runtime", "backend.api.device")


@pytest.fixture
def device_api(monkeypatch, tmp_path):
    for name in _RELOADED:
        sys.modules.pop(name, None)
    (tmp_path / "page" / "assets").mkdir(parents=True)
    (tmp_path / "resource").mkdir()

    interface = InterfaceModel.model_validate(
        {
            "interface_version": 2,
            "name": "Test",
            "controller": [
                {"name": "ADB", "label": "ADB", "type": "Adb"},
                {"name": "PC", "label": "PC", "type": "Win32"},
            ],
            "resource": [
                {"name": "none", "path": [], "controller": None},
                {"name": "empty", "path": [], "controller": []},
                {"name": "adb", "path": [], "controller": ["ADB"]},
                {"name": "pc", "path": [], "controller": ["PC"]},
                {"name": "both", "path": [], "controller": ["ADB", "PC"]},
            ],
            "task": [],
        }
    )
    monkeypatch.setattr(
        "backend.models.interface_loader.load_interface_model",
        lambda _app_root: interface,
    )

    module = importlib.import_module("backend.api.device")
    try:
        yield module
    finally:
        for name in _RELOADED:
            sys.modules.pop(name, None)


@pytest.mark.parametrize(
    ("controller_type", "expected_names"),
    [
        (None, ["none", "empty", "adb", "pc", "both"]),
        ("", ["none", "empty", "adb", "pc", "both"]),
        ("Win32", ["none", "empty", "pc", "both"]),
        ("Unknown", ["none", "empty"]),
    ],
)
def test_get_resource_filters_by_controller_type(
    device_api,
    controller_type,
    expected_names,
):
    response = device_api.get_resource(controller_type)

    assert response["status"] == "success"
    assert [resource["name"] for resource in response["resource"]] == expected_names
