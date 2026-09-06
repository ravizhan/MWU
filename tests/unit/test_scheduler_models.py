"""Tests for models/scheduler.py — Pydantic model validation contracts."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from models.scheduler import (
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
    ManualStartPayload,
    PortableCronStr,
    PreTaskCommand,
    ScheduledTaskCreate,
    ScheduledTaskDeviceConfig,
    TaskName,
    TriggerConfig,
)

_CORPUS_PATH = Path(__file__).parent.parent / "fixtures" / "validation_contract.json"


def _load_corpus():
    with open(_CORPUS_PATH, encoding="utf-8") as f:
        return json.load(f)


_CORPUS = _load_corpus()
_portable_adapter = TypeAdapter(PortableCronStr)
_trigger_adapter = TypeAdapter(TriggerConfig)


class TestCronStr:
    @pytest.mark.parametrize("case", _CORPUS, ids=[c["name"] for c in _CORPUS])
    def test_corpus(self, case):
        try:
            result = _portable_adapter.validate_python(case["input"])
            valid = True
            canonical = str(result)
        except Exception:
            valid = False
            canonical = None
        assert valid == case["valid"]
        if case["valid"]:
            assert canonical == case["canonical"]


class TestTriggerConfig:
    def test_cron_discriminated(self):
        raw = {"type": "cron", "cron": "0 9 * * *"}
        result = _trigger_adapter.validate_python(raw)
        assert isinstance(result, CronTriggerConfig)

    def test_date_discriminated(self):
        raw = {"type": "date", "run_date": "2026-12-31T00:00:00"}
        result = _trigger_adapter.validate_python(raw)
        assert isinstance(result, DateTriggerConfig)

    def test_interval_discriminated(self):
        raw = {"type": "interval", "hours": 1}
        result = _trigger_adapter.validate_python(raw)
        assert isinstance(result, IntervalTriggerConfig)

    def test_unknown_type_rejected(self):
        with pytest.raises(ValidationError):
            _trigger_adapter.validate_python({"type": "unknown"})

    def test_cron_model_dump_json(self):
        config = CronTriggerConfig(cron="0 9 * * *")
        dump = config.model_dump(mode="json")
        assert isinstance(dump["cron"], str)
        assert dump["type"] == "cron"


class TestTaskName:
    _adapter = TypeAdapter(TaskName)

    def test_valid(self):
        assert self._adapter.validate_python("my task") == "my task"

    def test_stripped(self):
        assert self._adapter.validate_python("  hello  ") == "hello"

    def test_empty_rejected(self):
        with pytest.raises(ValidationError):
            self._adapter.validate_python("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValidationError):
            self._adapter.validate_python("   ")

    def test_too_long_rejected(self):
        with pytest.raises(ValidationError):
            self._adapter.validate_python("x" * 101)


class TestPreTaskCommand:
    def test_timeout_bounds(self):
        cmd = PreTaskCommand(command="echo hi", timeout=1)
        assert cmd.timeout == 1
        cmd = PreTaskCommand(command="echo hi", timeout=3600)
        assert cmd.timeout == 3600

    def test_timeout_zero_rejected(self):
        with pytest.raises(ValidationError):
            PreTaskCommand(command="echo hi", timeout=0)

    def test_timeout_too_large_rejected(self):
        with pytest.raises(ValidationError):
            PreTaskCommand(command="echo hi", timeout=3601)


class TestIntervalTriggerConfig:
    def test_end_before_start_rejected(self):
        with pytest.raises(ValidationError, match="end_date"):
            IntervalTriggerConfig(
                hours=1,
                start_date=datetime(2026, 6, 1, tzinfo=UTC),
                end_date=datetime(2026, 1, 1, tzinfo=UTC),
            )

    def test_valid_interval(self):
        config = IntervalTriggerConfig(hours=1)
        assert config.hours == 1

    def test_zero_interval_rejected(self):
        with pytest.raises(ValidationError):
            IntervalTriggerConfig()


class TestScheduledTaskCreate:
    def test_requires_task_list(self):
        with pytest.raises(ValidationError):
            ScheduledTaskCreate(
                name="test",
                trigger_config={"type": "cron", "cron": "0 9 * * *"},
                task_list=[],
            )

    def test_valid_create(self):
        task = ScheduledTaskCreate(
            task_identity="name",
            name="test",
            trigger_config={"type": "cron", "cron": "0 9 * * *"},
            task_list=["task1"],
        )
        assert task.name == "test"

    def test_name_stripped(self):
        task = ScheduledTaskCreate(
            task_identity="name",
            name="  hello  ",
            trigger_config={"type": "cron", "cron": "0 9 * * *"},
            task_list=["task1"],
        )
        assert task.name == "hello"


class TestScheduledTaskDeviceConfig:
    def test_adb_serial_allowed(self):
        d = ScheduledTaskDeviceConfig(
            controller_name="c", device_type="Adb", device_address="emulator-5554"
        )
        assert d.device_address == "emulator-5554"

    def test_adb_ipv4_canonicalized(self):
        d = ScheduledTaskDeviceConfig(
            controller_name="c", device_type="Adb", device_address=" 192.168.1.1:5555 "
        )
        assert d.device_address == "192.168.1.1:5555"

    def test_playcover_must_be_ipv4(self):
        with pytest.raises(ValidationError):
            ScheduledTaskDeviceConfig(
                controller_name="c", device_type="PlayCover", device_address="not-an-ip"
            )

    def test_win32_positive(self):
        d = ScheduledTaskDeviceConfig(
            controller_name="c", device_type="Win32", device_address="12345"
        )
        assert d.device_address == "12345"

    def test_gamepad_valid(self):
        d = ScheduledTaskDeviceConfig(
            controller_name="c", device_type="Gamepad", device_address="12345|1"
        )
        assert d.device_address == "12345|1"

    def test_macos_cgwindow_id(self):
        d = ScheduledTaskDeviceConfig(
            controller_name="c",
            device_type="MacOS",
            device_address=" 0042 ",
        )
        assert d.device_address == "42"

    def test_macos_non_positive_rejected(self):
        with pytest.raises(ValidationError):
            ScheduledTaskDeviceConfig(
                controller_name="c",
                device_type="MacOS",
                device_address="0",
            )

    def test_linux_json_address(self):
        d = ScheduledTaskDeviceConfig(
            controller_name="c",
            device_type="Linux",
            device_address=(
                '{"wlr_socket_path": "/run/user/1000/wayland-1", "kind": "wlr"}'
            ),
        )
        assert (
            d.device_address
            == '{"kind": "wlr", "wlr_socket_path": "/run/user/1000/wayland-1"}'
        )

    def test_linux_invalid_json_rejected(self):
        with pytest.raises(ValidationError):
            ScheduledTaskDeviceConfig(
                controller_name="c",
                device_type="Linux",
                device_address="not-json",
            )


class TestManualStartPayload:
    def test_requires_task_list(self):
        with pytest.raises(ValidationError):
            ManualStartPayload(
                controller_name="c",
                device={
                    "controller_name": "c",
                    "device_type": "Adb",
                    "device_address": "127.0.0.1:5555",
                },
                resource_name="r",
                task_list=[],
            )

    def test_requires_controller_name(self):
        with pytest.raises(ValidationError):
            ManualStartPayload(
                controller_name="",
                device={
                    "controller_name": "c",
                    "device_type": "Adb",
                    "device_address": "127.0.0.1:5555",
                },
                resource_name="r",
                task_list=["t1"],
            )
