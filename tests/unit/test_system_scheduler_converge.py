"""Tests for services/system_scheduler.py — converge semantics with a fake backend."""

from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from models.scheduler import CronTriggerConfig, DateTriggerConfig, ScheduledTask
from services.system_scheduler import SystemScheduler
from services.system_scheduler_backend import SystemSchedulerBackend

T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"
T3 = "33333333-3333-4333-8333-333333333333"
T4 = "44444444-4444-4444-8444-444444444444"
ORPHAN_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ORPHAN_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
GHOST = "99999999-9999-4999-8999-999999999999"


def _uuid(task_id: str) -> str:
    """确保测试用任务 ID 为合法 UUID（_build_spec 会经 validate_task_id 校验）。"""
    assert UUID(task_id).version == 4
    return task_id


class FakeBackend(SystemSchedulerBackend):
    """记录 register/unregister 调用并可编程失败的测试后端替身。"""

    def __init__(
        self,
        pre_registered=(),
        fail_register=(),
        fail_unregister=(),
        list_raises=False,
    ):
        self.registered = set(pre_registered)
        self.fail_register = set(fail_register)
        self.fail_unregister = set(fail_unregister)
        self.list_raises = list_raises
        self.register_calls: list[str] = []
        self.unregister_calls: list[str] = []

    def register(self, spec):
        self.register_calls.append(spec.task_id)
        if spec.task_id in self.fail_register:
            raise RuntimeError(f"register failed: {spec.task_id}")
        self.registered.add(spec.task_id)

    def unregister(self, task_id):
        self.unregister_calls.append(task_id)
        if task_id in self.fail_unregister:
            raise RuntimeError(f"unregister failed: {task_id}")
        self.registered.discard(task_id)

    def list_registered_task_ids(self):
        if self.list_raises:
            raise RuntimeError("list failed")
        return set(self.registered)


def make_task(task_id: str, wakeup_enabled=True, enabled=True) -> ScheduledTask:
    return ScheduledTask(
        task_identity="name",
        id=_uuid(task_id),
        name=f"任务{task_id}",
        wakeup_enabled=wakeup_enabled,
        enabled=enabled,
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
    )


def make_scheduler(backend: FakeBackend) -> SystemScheduler:
    return SystemScheduler(Path("D:/app"), backend=backend)


class TestConvergeDesiredFiltering:
    def test_registers_only_wakeup_enabled_and_enabled(self):
        backend = FakeBackend()
        scheduler = make_scheduler(backend)
        desired = [
            make_task(T1),  # 唤醒 + 启用 → 注册
            make_task(T2, wakeup_enabled=True, enabled=False),  # 唤醒但停用
            make_task(T3, wakeup_enabled=False, enabled=True),  # 启用但未开唤醒
            make_task(T4, wakeup_enabled=False, enabled=False),
        ]

        report = scheduler.converge(desired)

        assert report.registered == [T1]
        assert report.unregistered == []
        assert report.failed == {}
        assert backend.register_calls == [T1]
        assert backend.unregister_calls == []
        assert backend.registered == {T1}


class TestConvergeOrphanCleanup:
    def test_unregisters_orphans_sorted(self):
        backend = FakeBackend(pre_registered=[T1, ORPHAN_B, ORPHAN_A])
        scheduler = make_scheduler(backend)

        report = scheduler.converge([make_task(T1)])

        assert report.registered == [T1]
        assert report.unregistered == [ORPHAN_A, ORPHAN_B]  # 排序稳定
        assert report.failed == {}
        assert backend.unregister_calls == [ORPHAN_A, ORPHAN_B]
        assert backend.registered == {T1}


class TestConvergeFailureIsolation:
    def test_failing_register_lands_in_failed_and_does_not_abort_others(self):
        backend = FakeBackend(fail_register={T2})
        scheduler = make_scheduler(backend)

        report = scheduler.converge([make_task(T1), make_task(T2), make_task(T3)])

        assert report.registered == [T1, T3]
        assert T2 in report.failed
        assert "register failed" in report.failed[T2]
        # T2 的注册尝试确实发生，且未中断 T1/T3
        assert backend.register_calls == [T1, T2, T3]
        assert backend.unregister_calls == []
        assert backend.registered == {T1, T3}

    def test_failing_unregister_lands_in_failed(self):
        backend = FakeBackend(pre_registered=[T1, ORPHAN_A], fail_unregister={ORPHAN_A})
        scheduler = make_scheduler(backend)

        report = scheduler.converge([make_task(T1)])

        assert report.registered == [T1]
        assert report.unregistered == []
        assert ORPHAN_A in report.failed
        assert "unregister failed" in report.failed[ORPHAN_A]
        assert backend.unregister_calls == [ORPHAN_A]

    def test_list_failure_records_sentinel_and_no_side_effects(self):
        backend = FakeBackend(pre_registered=[GHOST], list_raises=True)
        scheduler = make_scheduler(backend)

        report = scheduler.converge([make_task(T1)])

        # 查询失败 → 当前状态未知，不做任何注册/清理，仅记录失败
        assert report.registered == []
        assert report.unregistered == []
        assert set(report.failed) == {"__list__"}
        assert "list failed" in report.failed["__list__"]
        assert backend.register_calls == []
        assert backend.unregister_calls == []

    def test_all_fail_still_returns_report_without_raising(self):
        backend = FakeBackend(fail_register={T1, T2})
        scheduler = make_scheduler(backend)

        report = scheduler.converge([make_task(T1), make_task(T2)])

        assert report.registered == []
        assert set(report.failed) == {T1, T2}


class TestNonCronTrigger:
    def test_register_rejects_non_cron(self):
        backend = FakeBackend()
        scheduler = make_scheduler(backend)
        task = ScheduledTask(
            task_identity="name",
            id="date-1",
            name="日期任务",
            wakeup_enabled=True,
            enabled=True,
            trigger_config=DateTriggerConfig(run_date=datetime(2026, 1, 1, 9, 0)),
        )

        with pytest.raises(ValueError, match="仅 Cron 触发器支持系统级唤醒"):
            scheduler.register(task)

    def test_converge_records_non_cron_in_failed(self):
        backend = FakeBackend()
        scheduler = make_scheduler(backend)
        task = ScheduledTask(
            task_identity="name",
            id="date-1",
            name="日期任务",
            wakeup_enabled=True,
            enabled=True,
            trigger_config=DateTriggerConfig(run_date=datetime(2026, 1, 1, 9, 0)),
        )

        report = scheduler.converge([task])

        assert report.registered == []
        assert "date-1" in report.failed
        assert "仅 Cron" in report.failed["date-1"]


class NullLikeBackend(FakeBackend):
    """模拟不支持 OS 原生唤醒的后端（supports_native=False）。"""

    supports_native = False


class TestConvergeNonNativeBackend:
    def test_converge_is_noop_when_backend_lacks_native_support(self):
        backend = NullLikeBackend(pre_registered={ORPHAN_A})
        scheduler = make_scheduler(backend)

        report = scheduler.converge([make_task(T1), make_task(T2)])

        # 不注册、不清理孤儿，留给调度层回退到应用内派发
        assert report.registered == []
        assert report.unregistered == []
        assert report.failed == {}
        assert backend.register_calls == []
        assert backend.unregister_calls == []

    def test_supports_native_property_reflects_backend(self):
        assert make_scheduler(FakeBackend()).supports_native is True
        assert make_scheduler(NullLikeBackend()).supports_native is False


class TestNonNativeRegisterUnregister:
    def test_register_is_noop_when_backend_lacks_native_support(self):
        backend = NullLikeBackend()
        scheduler = make_scheduler(backend)
        # 非法/非 Cron 触发器也不会被解析：supports_native=False 时直接跳过
        task = ScheduledTask(
            task_identity="name",
            id="date-1",
            name="日期任务",
            wakeup_enabled=True,
            enabled=True,
            trigger_config=DateTriggerConfig(run_date=datetime(2026, 1, 1, 9, 0)),
        )

        scheduler.register(task)

        assert backend.register_calls == []

    def test_unregister_is_noop_when_backend_lacks_native_support(self):
        backend = NullLikeBackend()
        scheduler = make_scheduler(backend)

        scheduler.unregister(T1)

        assert backend.unregister_calls == []
