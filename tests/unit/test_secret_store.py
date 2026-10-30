"""密码字段加密存储测试：写盘为密文、加载还原明文、密钥丢失后清空。"""

from collections.abc import Iterator
from pathlib import Path

import pytest

import secret_store
from models.interface import Controller, InputCase, InterfaceModel, Option, Resource
from models.settings import SettingsModel
from settings_io import load_settings_model, write_settings_preserving_custom_devices


def _interface(with_password_option: bool) -> InterfaceModel:
    option = (
        {
            "login": Option(
                type="input", inputs=[InputCase(name="password", password=True)]
            )
        }
        if with_password_option
        else None
    )
    return InterfaceModel(
        interface_version=2,
        name="Test",
        controller=[Controller(name="adb", type="Adb")],
        resource=[Resource(name="main", path=["resource"])],
        option=option,
    )


@pytest.fixture
def key_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "secret.key"
    monkeypatch.setattr(secret_store, "_key_path", lambda: path)
    secret_store._fernet.cache_clear()
    secret_store.configure(_interface(with_password_option=True))
    yield path
    secret_store._fernet.cache_clear()
    secret_store.configure(_interface(with_password_option=False))


def _write_password_settings(path: Path) -> None:
    write_settings_preserving_custom_devices(
        path,
        SettingsModel(globalOptionValues={"login": {"password": "hunter2"}}),
    )


def test_password_is_encrypted_on_disk_and_plain_on_load(
    tmp_path: Path, key_path: Path
) -> None:
    path = tmp_path / "settings.json"
    _write_password_settings(path)

    assert "hunter2" not in path.read_text(encoding="utf-8")
    settings = load_settings_model(path)
    assert settings.globalOptionValues["login"] == {"password": "hunter2"}


def test_missing_key_yields_empty_password(tmp_path: Path, key_path: Path) -> None:
    path = tmp_path / "settings.json"
    _write_password_settings(path)

    key_path.unlink()
    secret_store._fernet.cache_clear()

    settings = load_settings_model(path)
    assert settings.globalOptionValues["login"] == {"password": ""}
