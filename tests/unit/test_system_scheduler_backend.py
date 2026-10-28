"""Tests for services/system_scheduler_backend.py — OS error-path handling.

后端通过 subprocess.run 调用系统 CLI；这里用 monkeypatch 模拟命令失败的
各种形态，验证“无任务/任务不存在”与真实错误被正确区分（前者视为成功/
空集合，后者必须上抛，避免误清用户状态）。
"""

import subprocess
from pathlib import Path

import pytest

from services.system_scheduler_backend import (
    CommandError,
    LinuxBackend,
    MacOSBackend,
    WindowsBackend,
)


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _error(stdout="", stderr=""):
    return subprocess.CalledProcessError(
        returncode=1, cmd=["crontab", "-l"], output=stdout, stderr=stderr
    )


class TestLinuxCrontabReadSafety:
    def test_no_crontab_returns_empty(self, monkeypatch):
        backend = LinuxBackend()

        def fake_run(args, **kwargs):
            raise _error(stderr="crontab: no crontab for root\n")

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        assert backend._read_crontab() == ""

    def test_other_error_raises_runtime_error(self, monkeypatch):
        backend = LinuxBackend()

        def fake_run(args, **kwargs):
            raise _error(stderr="crontab: can't open your crontab file: 权限不够\n")

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        with pytest.raises(RuntimeError, match="读取 crontab 失败"):
            backend._read_crontab()

    def test_oserror_raises_runtime_error(self, monkeypatch):
        backend = LinuxBackend()

        def fake_run(args, **kwargs):
            raise OSError("crontab 不存在")

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        with pytest.raises(RuntimeError, match="读取 crontab 失败"):
            backend._read_crontab()

    def test_multiline_crontab_list(self, monkeypatch):
        backend = LinuxBackend()
        content = (
            "# MWU:11111111-1111-4111-8111-111111111111\n"
            "0 9 * * * /usr/bin/python\n"
            "# MWU:22222222-2222-4222-8222-222222222222\n"
        )

        def fake_run(args, **kwargs):
            return _completed(stdout=content)

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        assert backend.list_registered_task_ids() == {
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        }


class TestWindowsQueryFailure:
    def make_backend(self, monkeypatch, fake_run):
        backend = WindowsBackend()
        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        return backend

    def test_no_tasks_in_stderr_returns_empty(self, monkeypatch):
        def fake_run(args, **kwargs):
            raise subprocess.CalledProcessError(
                1, args, output="", stderr="ERROR: No scheduled tasks are available.\n"
            )

        backend = self.make_backend(monkeypatch, fake_run)
        assert backend.list_registered_task_ids() == set()

    def test_real_error_raises(self, monkeypatch):
        def fake_run(args, **kwargs):
            raise subprocess.CalledProcessError(
                1, args, output="", stderr="ERROR: Access is denied.\n"
            )

        backend = self.make_backend(monkeypatch, fake_run)
        with pytest.raises(CommandError):
            backend.list_registered_task_ids()


class TestWindowsUnregisterIdempotent:
    def test_not_found_is_success(self, monkeypatch):
        backend = WindowsBackend()

        def fake_run(args, **kwargs):
            raise subprocess.CalledProcessError(
                1,
                args,
                output="",
                stderr="ERROR: The system cannot find the file specified.\n",
            )

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        # 不抛错即为幂等成功
        backend.unregister("11111111-1111-4111-8111-111111111111")

    def test_other_error_propagates(self, monkeypatch):
        backend = WindowsBackend()

        def fake_run(args, **kwargs):
            raise subprocess.CalledProcessError(
                1, args, output="", stderr="ERROR: Access is denied.\n"
            )

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        with pytest.raises(CommandError):
            backend.unregister("11111111-1111-4111-8111-111111111111")


class TestMacOSListRegistered:
    def test_oserror_propagates(self, monkeypatch, tmp_path):
        backend = MacOSBackend()
        plist_dir = tmp_path / "LaunchAgents"
        plist_dir.mkdir()

        def _boom(*_args, **_kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(MacOSBackend, "_PLIST_DIR", plist_dir)
        monkeypatch.setattr(Path, "glob", _boom)

        # 未知状态必须上抛，避免把「读不到」当成「没有任务」而误清孤儿
        with pytest.raises(RuntimeError, match="查询 macOS 计划任务失败"):
            backend.list_registered_task_ids()


class TestMacOSBootout:
    def _bootout_run(self, returncode, stderr):
        def fake_run(args, **kwargs):
            assert args[0] == "launchctl"
            assert args[1] == "bootout"
            return _completed(stderr=stderr, returncode=returncode)

        return fake_run

    def test_not_loaded_bootout_is_success(self, monkeypatch):
        backend = MacOSBackend()
        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run",
            self._bootout_run(3, "Boot-out failed: 3: No such process"),
        )
        # 不抛错即为幂等成功
        backend._bootout(501, "com.mwu.scheduler.11111111-1111-4111-8111-111111111111")

    def test_other_bootout_error_propagates(self, monkeypatch):
        backend = MacOSBackend()
        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run",
            self._bootout_run(1, "launchctl: Error: the job was not properly loaded"),
        )
        # 真实错误（与“未加载”无关）必须上抛，避免误删 plist
        with pytest.raises(CommandError, match="launchctl bootout 失败"):
            backend._bootout(
                501, "com.mwu.scheduler.11111111-1111-4111-8111-111111111111"
            )
