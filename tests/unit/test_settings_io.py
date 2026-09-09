"""Tests for settings_io device-type preprocessing on load."""

import json
from pathlib import Path

import settings_io
from models.settings import SettingsModel, TelemetryConsent

# 被移除的旧设备类型名（pydantic DeviceType 已不接受）。
_LEGACY_TYPE = "Wl" + "Roots"
_LEGACY_ADDRESS = "/run/user/1000/wayland-1"


def _write_settings(path: Path, raw: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")


class TestLoadSettingsPrunesIllegalDeviceTypes:
    def _path(self, tmp_path: Path) -> Path:
        return tmp_path / "config" / "settings.json"

    def test_legacy_last_connected_pruned_rest_preserved(self, tmp_path: Path):
        path = self._path(tmp_path)
        _write_settings(
            path,
            {
                "panel": {
                    "lastConnectedDevice": {
                        "type": _LEGACY_TYPE,
                        "controller_name": "W",
                        "address": _LEGACY_ADDRESS,
                    },
                    "recentDevices": [
                        {
                            "type": _LEGACY_TYPE,
                            "controller_name": "W",
                            "address": _LEGACY_ADDRESS,
                        },
                        {
                            "type": "Adb",
                            "controller_name": "A",
                            "address": "127.0.0.1:5555",
                        },
                    ],
                    "customDevices": [
                        {
                            "type": _LEGACY_TYPE,
                            "controller_name": "W",
                            "address": "/x",
                        },
                        {
                            "type": "Adb",
                            "controller_name": "A",
                            "address": "10.0.0.1:5555",
                        },
                    ],
                },
                "runtime": {"timeout": 555},
            },
        )

        model = settings_io.load_settings_model(path)

        assert model.runtime.timeout == 555
        assert model.panel.lastConnectedDevice is None
        assert model.panel.recentDevices is not None
        assert len(model.panel.recentDevices) == 1
        assert model.panel.recentDevices[0].type == "Adb"
        assert len(model.panel.customDevices) == 1
        assert model.panel.customDevices[0].type == "Adb"

    def test_all_legal_types_kept(self, tmp_path: Path):
        path = self._path(tmp_path)
        legal = {
            "Adb": "emulator-5554",
            "Win32": "100",
            "MacOS": "42",
            "Gamepad": "42|0",
            "PlayCover": "127.0.0.1:1717",
            "Linux": '{"kind": "wlr", "wlr_socket_path": "/run/user/1000/wayland-1"}',
        }
        _write_settings(
            path,
            {
                "panel": {
                    "customDevices": [
                        {"type": t, "controller_name": t, "address": a}
                        for t, a in legal.items()
                    ],
                    # recentDevices 校验时会截断为 5 条；用 customDevices 覆盖全部类型
                    "recentDevices": [
                        {"type": t, "controller_name": t, "address": a}
                        for t, a in list(legal.items())[:3]
                    ],
                }
            },
        )
        model = settings_io.load_settings_model(path)
        assert model.panel.recentDevices is not None
        assert len(model.panel.recentDevices) == 3
        assert len(model.panel.customDevices) == len(legal)

    def test_invalid_type_falls_back_to_defaults(self, tmp_path: Path):
        """预处理后仍无法校验（如 runtime.timeout 非法）才整体回退默认。"""
        path = self._path(tmp_path)
        _write_settings(
            path,
            {
                "panel": {
                    "lastConnectedDevice": {
                        "type": _LEGACY_TYPE,
                        "controller_name": "W",
                        "address": _LEGACY_ADDRESS,
                    }
                },
                "runtime": {"timeout": 5},  # 越界：仍无法校验
            },
        )
        model = settings_io.load_settings_model(path)
        assert isinstance(model, SettingsModel)
        assert model.runtime.timeout == 300  # 默认值

    def test_non_dict_panel_ignored(self, tmp_path: Path):
        path = self._path(tmp_path)
        _write_settings(path, {"panel": "not-a-dict"})
        model = settings_io.load_settings_model(path)
        assert model.panel.customDevices == []

    def test_prune_logs_warning_for_removed_type(self, tmp_path: Path, caplog):
        path = self._path(tmp_path)
        _write_settings(
            path,
            {
                "panel": {
                    "customDevices": [
                        {
                            "type": _LEGACY_TYPE,
                            "controller_name": "W",
                            "address": "/x",
                        },
                    ]
                }
            },
        )
        with caplog.at_level("WARNING", logger="mwu.settings_io"):
            model = settings_io.load_settings_model(path)
        assert model.panel.customDevices == []
        assert any(_LEGACY_TYPE in record.getMessage() for record in caplog.records)


def test_normal_settings_write_preserves_disk_owned_fields(tmp_path: Path):
    path = tmp_path / "config" / "settings.json"
    disk = {
        "panel": {
            "customDevices": [
                {"type": "Adb", "controller_name": "A", "address": "device"}
            ]
        },
        "telemetry": {
            "consent": "granted",
            "configId": "disk-target",
            "failureAttachments": True,
        },
    }
    _write_settings(path, disk)

    incoming = SettingsModel(
        telemetry=TelemetryConsent(
            consent="denied", configId="stale-target", failureAttachments=False
        )
    )
    written = settings_io.write_settings_preserving_protected(path, incoming)

    assert written["panel"]["customDevices"] == disk["panel"]["customDevices"]
    assert written["telemetry"] == disk["telemetry"]
