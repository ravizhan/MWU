import importlib
import sys

import pytest

from backend.models.interface import InterfaceModel

_RELOADED = ("backend.runtime", "backend.api.interface")


@pytest.fixture
def interface_api(monkeypatch):
    for name in _RELOADED:
        sys.modules.pop(name, None)
    interface = InterfaceModel.model_validate(
        {
            "interface_version": 2,
            "name": "Test",
            "controller": [{"name": "ADB", "type": "Adb"}],
            "resource": [{"name": "main", "path": []}],
            "task": [],
        }
    )
    monkeypatch.setattr(
        "backend.models.interface_loader.load_interface_model",
        lambda _project_dir: interface,
    )
    module = importlib.import_module("backend.api.interface")
    try:
        yield module
    finally:
        for name in _RELOADED:
            sys.modules.pop(name, None)


def test_lists_one_level_with_directories_first(interface_api, tmp_path):
    (tmp_path / "resource" / "image").mkdir(parents=True)
    (tmp_path / "resource" / "b.json").write_text("{}")
    (tmp_path / "resource" / "A.json").write_text("{}")

    response = interface_api.list_project_dir("./resource")

    assert response["status"] == "success"
    assert [(e.path, e.is_dir) for e in response["entries"]] == [
        ("resource/image", True),
        ("resource/A.json", False),
        ("resource/b.json", False),
    ]


@pytest.mark.parametrize("path", ["../", "resource/../..", "C:/Windows", "missing"])
def test_rejects_paths_outside_or_missing(interface_api, tmp_path, path):
    (tmp_path / "resource").mkdir()

    response = interface_api.list_project_dir(path)

    assert response.status_code == 400
