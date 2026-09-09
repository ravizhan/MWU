import importlib
import sys

import pytest

from models.interface import InterfaceModel


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
        "models.interface_loader.load_interface_model",
        lambda _app_root: interface,
    )

    module = importlib.import_module("main")
    try:
        yield module
    finally:
        sys.modules.pop("main", None)


@pytest.mark.parametrize(
    ("controller_type", "expected_names"),
    [
        (None, ["none", "empty", "adb", "pc", "both"]),
        ("Win32", ["none", "empty", "pc", "both"]),
        ("Unknown", ["none", "empty"]),
    ],
)
def test_get_resource_filters_by_controller_type(
    isolated_main,
    controller_type,
    expected_names,
):
    isolated_main.app_state.worker = object()

    response = isolated_main.get_resource(controller_type)

    assert response["status"] == "success"
    assert [resource["name"] for resource in response["resource"]] == expected_names


def test_get_resource_requires_worker(isolated_main):
    isolated_main.app_state.worker = None

    assert isolated_main.get_resource(None) == {
        "status": "failed",
        "message": "Worker未初始化",
    }
