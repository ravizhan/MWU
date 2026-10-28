"""SchedulerManager CRUD、原生唤醒顺序与触发器往返测试。"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from apscheduler.triggers.cron import CronTrigger

from app_state import AppState
from models.interface import Controller, InterfaceModel, Resource, Task
from models.scheduler import (
    CronTriggerConfig,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
)
from scheduler_manager import SchedulerManager
from services.system_scheduler import ConvergeReport


def make_create(
    name: str,
    wakeup_enabled: bool = False,
    enabled: bool = True,
    cron: str = "0 9 * * *",
) -> ScheduledTaskCreate:
    return ScheduledTaskCreate(
        name=name,
        wakeup_enabled=wakeup_enabled,
        enabled=enabled,
        trigger_config=CronTriggerConfig(cron=cron),
        task_list=["Startup"],
    )


class _StubEvents:
    def send_log(self, *_args, **_kwargs):
        pass

    def send_notification(self, *_args, **_kwargs):
        pass


class _StubWorker:
    def __init__(self):
        self.interface = InterfaceModel(
            interface_version=2,
            name="Test",
            controller=[Controller(name="adb", type="Adb")],
            resource=[Resource(name="main", path=["resource"])],
            task=[Task(name="Startup", entry="Startup")],
        )
        self.events = _StubEvents()


@pytest.fixture
async def manager_env(tmp_path: Path):
    state = AppState()
    state.worker = _StubWorker()
    system_scheduler = MagicMock()
    system_scheduler.converge.return_value = ConvergeReport()
    mgr = SchedulerManager(
        state, tmp_path / "scheduler.sqlite", system_scheduler=system_scheduler
    )
    await mgr.initialize(paused=True)
    assert mgr.scheduler is not None
    mgr.scheduler.resume()
    system_scheduler.reset_mock()
    try:
        yield mgr, state, system_scheduler
    finally:
        await mgr.shutdown()


class TestCreateTaskWakeupFirst:
    async def test_register_called_before_aps_job_exists(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        seen: list[str] = []

        def _record(task):
            # 注册发生在 APS 落库之前：此刻 get_job 必须为 None
            assert mgr.scheduler.get_job(task.id) is None
            seen.append(task.id)

        system_scheduler.register.side_effect = _record

        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))

        assert system_scheduler.register.call_count == 1
        assert seen == [task.id]
        assert mgr.scheduler.get_job(task.id) is not None
        assert task.wakeup_enabled is True

        # get_task 解码还原 wakeup_enabled 与 trigger_config
        got = await mgr.get_task(task.id)
        assert got is not None
        assert got.wakeup_enabled is True
        assert got.trigger_config.cron == "0 9 * * *"

    async def test_register_failure_aborts_creation_and_propagates(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        captured: dict[str, str] = {}

        def _boom(task):
            captured["id"] = task.id
            raise RuntimeError("native register boom")

        system_scheduler.register.side_effect = _boom

        with pytest.raises(RuntimeError, match="native register boom"):
            await mgr.create_task(make_create("失败任务", wakeup_enabled=True))

        # APS 任务未落库
        assert mgr.scheduler.get_job(captured["id"]) is None
        assert await mgr.get_task(captured["id"]) is None

    async def test_no_wakeup_skips_register(self, manager_env):
        mgr, _state, system_scheduler = manager_env

        task = await mgr.create_task(make_create("普通任务", wakeup_enabled=False))

        system_scheduler.register.assert_not_called()
        assert mgr.scheduler.get_job(task.id) is not None

    async def test_disabled_task_with_wakeup_skips_register(self, manager_env):
        # _desired_wakeup = wakeup_enabled AND enabled
        mgr, _state, system_scheduler = manager_env

        task = await mgr.create_task(
            make_create("停用任务", wakeup_enabled=True, enabled=False)
        )

        system_scheduler.register.assert_not_called()
        assert mgr.scheduler.get_job(task.id) is not None


class TestTriggerRoundTrip:
    async def test_cron_trigger_round_trip_preserves_unix_dow(self, manager_env):
        mgr, _state, _system_scheduler = manager_env
        config = CronTriggerConfig(cron="0 9 * * 1")  # Unix 星期 1 = 周一

        trigger = mgr._create_trigger(config)

        assert isinstance(trigger, CronTrigger)
        # APS 0=周一 ↔ Unix 1=周一：构建时已转换
        dow_field = next(f for f in trigger.fields if f.name == "day_of_week")
        assert str(dow_field) == "0"

        decoded = mgr._build_trigger_config(trigger)
        assert isinstance(decoded, CronTriggerConfig)
        assert decoded.cron == "0 9 * * 1"


class TestUpdateTaskWakeup:
    async def test_turning_wakeup_off_unregisters(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        system_scheduler.register.assert_called_once()

        updated = await mgr.update_task(
            task.id, ScheduledTaskUpdate(wakeup_enabled=False)
        )

        assert updated is not None
        assert updated.wakeup_enabled is False
        system_scheduler.unregister.assert_called_once_with(task.id)

    async def test_disabling_task_with_wakeup_unregisters(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        system_scheduler.register.assert_called_once()

        updated = await mgr.update_task(task.id, ScheduledTaskUpdate(enabled=False))

        assert updated is not None
        assert updated.enabled is False
        system_scheduler.unregister.assert_called_once_with(task.id)

    async def test_reenabling_desired_task_registers_again(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        await mgr.update_task(task.id, ScheduledTaskUpdate(enabled=False))
        system_scheduler.unregister.assert_called_once()

        updated = await mgr.update_task(task.id, ScheduledTaskUpdate(enabled=True))

        assert updated is not None
        assert updated.enabled is True
        assert system_scheduler.register.call_count == 2


class TestScheduledJobFired:
    async def _make_kwargs(self, mgr, task) -> dict:
        job = mgr.scheduler.get_job(task.id)
        assert job is not None
        return job.kwargs

    async def test_wakeup_skips_in_app_dispatch_when_native_supported(
        self, manager_env, monkeypatch
    ):
        from maa_worker import execution
        from scheduler_manager import scheduled_job_fired

        mgr, state, system_scheduler = manager_env
        system_scheduler.supports_native = True
        state.system_scheduler = system_scheduler
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        submit = MagicMock()
        monkeypatch.setattr(execution, "submit_scheduled", submit)

        await scheduled_job_fired(**await self._make_kwargs(mgr, task))

        submit.assert_not_called()

    async def test_wakeup_falls_back_to_in_app_when_native_unsupported(
        self, manager_env, monkeypatch
    ):
        from maa_worker import execution
        from scheduler_manager import scheduled_job_fired

        mgr, state, system_scheduler = manager_env
        system_scheduler.supports_native = False
        state.system_scheduler = system_scheduler
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        captured: dict = {}

        async def fake_submit(state_arg, task_arg, origin):
            captured["origin"] = origin
            captured["task_id"] = task_arg.id

        monkeypatch.setattr(execution, "submit_scheduled", fake_submit)

        await scheduled_job_fired(**await self._make_kwargs(mgr, task))

        assert captured == {"origin": "in_app", "task_id": task.id}


class TestWakeupMinuteConflict:
    async def test_create_rejects_same_minute_wakeup(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        await mgr.create_task(
            make_create("任务A", wakeup_enabled=True, cron="0 9 * * *")
        )

        with pytest.raises(ValueError, match="同一分钟"):
            await mgr.create_task(
                make_create("任务B", wakeup_enabled=True, cron="0 9 * * 1")
            )

        # 冲突任务未注册、未落库
        assert system_scheduler.register.call_count == 1
        names = {t.name for t in await mgr.get_all_tasks()}
        assert names == {"任务A"}

    async def test_update_rejects_conflict_with_other_task(self, manager_env):
        mgr, _state, _system_scheduler = manager_env
        await mgr.create_task(
            make_create("任务A", wakeup_enabled=True, cron="0 9 * * *")
        )
        task_b = await mgr.create_task(
            make_create("任务B", wakeup_enabled=True, cron="30 10 * * *")
        )

        with pytest.raises(ValueError, match="同一分钟"):
            await mgr.update_task(
                task_b.id,
                ScheduledTaskUpdate(trigger_config=CronTriggerConfig(cron="0 9 * * *")),
            )

        # 任务 B 触发器保持原值
        got_b = await mgr.get_task(task_b.id)
        assert got_b is not None
        assert got_b.trigger_config.cron == "30 10 * * *"

    async def test_update_allows_self_unchanged(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        task = await mgr.create_task(
            make_create("任务A", wakeup_enabled=True, cron="0 9 * * *")
        )
        system_scheduler.register.assert_called_once()

        # 更新自身描述（cron 不变，应排除自身不报错）
        updated = await mgr.update_task(
            task.id, ScheduledTaskUpdate(description="新描述")
        )

        assert updated is not None
        assert updated.description == "新描述"


class TestNativeSync:
    async def test_pause_unregisters_only_active_wakeup(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        wakeup = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        plain = await mgr.create_task(make_create("普通任务", wakeup_enabled=False))
        system_scheduler.reset_mock()

        assert await mgr.pause_task(wakeup.id) is True
        system_scheduler.unregister.assert_called_once_with(wakeup.id)
        assert mgr.scheduler.get_job(wakeup.id).next_run_time is None

        system_scheduler.reset_mock()
        assert await mgr.pause_task(plain.id) is True
        system_scheduler.unregister.assert_not_called()

    async def test_resume_reregisters_native(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        await mgr.pause_task(task.id)
        system_scheduler.unregister.assert_called_once_with(task.id)

        assert await mgr.resume_task(task.id) is True
        assert system_scheduler.register.call_count == 2
        assert mgr.scheduler.get_job(task.id).next_run_time is not None

    async def test_delete_unregisters_only_active_wakeup(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        wakeup = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        plain = await mgr.create_task(make_create("普通任务", wakeup_enabled=False))
        system_scheduler.reset_mock()

        assert await mgr.delete_task(wakeup.id) is True
        system_scheduler.unregister.assert_called_once_with(wakeup.id)
        assert mgr.scheduler.get_job(wakeup.id) is None

        system_scheduler.reset_mock()
        assert await mgr.delete_task(plain.id) is True
        system_scheduler.unregister.assert_not_called()
        assert mgr.scheduler.get_job(plain.id) is None

    @pytest.mark.parametrize("op", ["pause", "resume", "delete"])
    async def test_missing_task_returns_false(self, manager_env, op):
        mgr, _state, _system_scheduler = manager_env

        assert await getattr(mgr, f"{op}_task")("no-such-task") is False

    @pytest.mark.parametrize(
        ("op", "failing_call"),
        [("pause", "unregister"), ("resume", "register"), ("delete", "unregister")],
    )
    async def test_native_failure_propagates_and_keeps_aps_state(
        self, manager_env, op, failing_call
    ):
        mgr, _state, system_scheduler = manager_env
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        if op == "resume":
            await mgr.pause_task(task.id)
        system_scheduler.reset_mock()
        getattr(system_scheduler, failing_call).side_effect = RuntimeError(
            "native boom"
        )

        with pytest.raises(RuntimeError, match="native boom"):
            await getattr(mgr, f"{op}_task")(task.id)

        job = mgr.scheduler.get_job(task.id)
        assert job is not None  # delete 未生效
        assert (job.next_run_time is None) == (op == "resume")

    async def test_update_native_failure_raises_after_aps_commit(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        system_scheduler.reset_mock()
        system_scheduler.register.side_effect = RuntimeError("native boom")

        with pytest.raises(RuntimeError, match="native boom"):
            await mgr.update_task(task.id, ScheduledTaskUpdate(description="新描述"))

        # APS 已提交，OS 侧由启动时 converge 修复
        updated = await mgr.get_task(task.id)
        assert updated is not None
        assert updated.description == "新描述"

    async def test_update_missing_task_returns_none(self, manager_env):
        mgr, _state, _system_scheduler = manager_env

        assert await mgr.update_task("no-such-task", ScheduledTaskUpdate()) is None
