"""Tests for maa_worker/execution.py — admission control and sqlite execution records.

worker 保持 None：后台执行协程以「Worker 未就绪」快速失败，断言最终落库状态。
"""

import asyncio
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app_state import AppState
from maa_worker.execution import (
    add_execution,
    finish_execution,
    init_db,
    list_executions,
    stop_active,
    submit_manual,
    submit_scheduled,
)
from maa_worker.pretask_service import PretaskError, PretaskStopped
from models.interface import Option, OptionCase
from models.scheduler import (
    CronTriggerConfig,
    ManualStartPayload,
    PreTaskCommand,
    ScheduledTask,
    ScheduledTaskDeviceConfig,
    TaskExecution,
)
from models.settings import SettingsModel


def make_payload(task_name: str = "Startup") -> ManualStartPayload:
    return ManualStartPayload(
        task_list=[task_name],
        controller_name="AdbController",
        device=ScheduledTaskDeviceConfig(
            controller_name="AdbController",
            device_type="Adb",
            device_address="127.0.0.1:5555",
        ),
        resource_name="main",
    )


def make_task(
    task_id: str = "task-1",
    name: str = "定时任务",
    *,
    with_payload: bool = False,
) -> ScheduledTask:
    """构造调度任务记录。

    with_payload=True 时补齐可执行载荷（任务名/控制器/设备/资源），与 make_payload
    对齐：缺少 device 或 resource_name 的调度任务会被 submit_scheduled 判为
    「设备或资源配置缺失」并立刻收尾，无法占据执行槽位。
    """
    return ScheduledTask(
        id=task_id,
        name=name,
        wakeup_enabled=True,
        enabled=True,
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Startup"] if with_payload else [],
        controller_name="AdbController" if with_payload else None,
        device=(
            ScheduledTaskDeviceConfig(
                controller_name="AdbController",
                device_type="Adb",
                device_address="127.0.0.1:5555",
            )
            if with_payload
            else None
        ),
        resource_name="main" if with_payload else None,
    )


async def _await_active_task(state: AppState) -> None:
    """等待当前活跃执行协程收尾（type-narrowing 辅助）。"""
    task = state.active_execution_task
    assert task is not None
    await task


# ---------------------------------------------------------------------------
# 用于前置阶段失败 / 停止 测试的伪 Worker（worker=None 时后台协程快速失败）
# ---------------------------------------------------------------------------


class _FakeEvents:
    def __init__(self):
        self.terminal_events: list[tuple[list[str], str | None, bool]] = []
        self.logs: list[str] = []

    def send_log(self, msg: str):
        self.logs.append(msg)

    def publish_task_terminal(self, task_list, run_label, succeeded, settings):
        self.terminal_events.append((list(task_list), run_label, succeeded))
        return SimpleNamespace(notify=[])

    def deliver_notification(self, event):
        pass

    @property
    def failed_events(self) -> list[tuple[list[str], str | None, bool]]:
        return [event for event in self.terminal_events if not event[2]]


class _FakeInterface:
    def __init__(self, names: list[str]):
        self.task = [
            SimpleNamespace(name=n, entry=f"Entry{n}", option=[]) for n in names
        ]
        self.option = {}
        self.global_option = []
        self.pretask = []
        self.controller = []
        self.resource = []


class _FakeTaskService:
    def __init__(self, result: bool, task_state: "_FakeTaskState | None" = None):
        self.result = result
        self.called = False
        self._task_state = task_state
        self.global_options = {}

    def start(
        self,
        task_list,
        options,
        task_name=None,
        pre_tasks=None,
        global_options=None,
        trace=None,
    ):
        self.called = True
        self.global_options = global_options or {}
        if self.result and self._task_state is not None:
            # 对齐真实 TaskService.start：成功时置 running=True
            self._task_state.running = True
        return self.result

    def stop(self) -> bool:
        return False


class _FakeSuccessfulTaskService(_FakeTaskService):
    def start(
        self,
        task_list,
        options,
        task_name=None,
        pre_tasks=None,
        global_options=None,
        trace=None,
    ):
        self.called = True
        self.global_options = global_options or {}
        if self._task_state is not None:
            self._task_state.running = True
            self._task_state.last_status = "success"
            self._task_state.running = False
        return True


class _FakePretaskService:
    def __init__(
        self,
        task_state: "_FakeTaskState | None" = None,
        ordering: list[str] | None = None,
    ):
        self.calls: list[tuple[str, str, list, dict]] = []
        self.stop_flags: list[bool] = []
        self.error: PretaskError | None = None
        self.set_stop_flag_on_error = False
        self._task_state = task_state
        self._ordering = ordering

    def run_all(
        self,
        controller_name,
        resource_name,
        user_pre_tasks,
        option_values,
    ):
        self.calls.append(
            (controller_name, resource_name, user_pre_tasks, option_values)
        )
        self.stop_flags.append(
            self._task_state.stop_flag if self._task_state is not None else False
        )
        if self._ordering is not None:
            self._ordering.append("pretask")
        if self.error is not None:
            if self.set_stop_flag_on_error and self._task_state is not None:
                self._task_state.stop_flag = True
            raise self.error


class _FakeDeviceState:
    connected = False
    configuration_locked = False
    controller_name = ""
    current_resource_name = ""


class _FakeDevice:
    """模拟慢速设备连接（connect 阻塞至 release 事件，供停止测试在准备阶段取消）。"""

    def __init__(
        self,
        *,
        ordering: list[str] | None = None,
        block: bool = True,
        fail_connect: bool = False,
    ):
        self.release = threading.Event()
        if not block:
            self.release.set()
        self.connect_called = False
        self.connect_calls = 0
        self.fail_connect = fail_connect
        self._ordering = ordering

    def build_device_model_from_config(self, controller_name, device_type, address):
        return SimpleNamespace(
            controller_name=controller_name,
            device_type=device_type,
            device_address=address,
        )

    def connect(self, model):
        self.connect_called = True
        self.connect_calls += 1
        if self._ordering is not None:
            self._ordering.append("connect")
        self.release.wait(timeout=5)
        return not self.fail_connect

    def set_resource(self, name):
        return True

    def reset_connection_state(self, reason: str | None = None):
        pass


class _FakeTaskState:
    def __init__(self):
        self.stop_flag = False
        self.running = False
        self.last_status = "idle"
        self.last_error = None


class _FakeWorker:
    def __init__(
        self,
        *,
        start_result: bool,
        ready: bool = False,
        block_connect: bool = False,
        ordering: list[str] | None = None,
    ):
        self.events = _FakeEvents()
        self.interface = _FakeInterface(["Startup"])
        self.task_state = _FakeTaskState()
        self.pretasks = _FakePretaskService(self.task_state, ordering)
        self.tasks = _FakeTaskService(start_result, task_state=self.task_state)
        self.device_state = _FakeDeviceState()
        self.device = (
            _FakeDevice(ordering=ordering, block=block_connect)
            if block_connect or ordering is not None
            else None
        )
        if ready:
            self.device_state.connected = True
            self.device_state.configuration_locked = True
            self.device_state.controller_name = "AdbController"
            self.device_state.current_resource_name = "main"


@pytest.fixture
def state(tmp_path: Path) -> AppState:
    st = AppState()
    st.scheduler_db_path = tmp_path / "scheduler.sqlite"
    init_db(st.scheduler_db_path)
    return st


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def _column_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as db:
        rows = db.execute("PRAGMA table_info(scheduler_executions)").fetchall()
    return {row[1] for row in rows}


# ---------------------------------------------------------------------------
# 持久化（stdlib sqlite3）
# ---------------------------------------------------------------------------


class TestSqlitePersistence:
    def test_init_db_creates_live_columns(self, tmp_path: Path):
        db_path = tmp_path / "executions.sqlite"

        init_db(db_path)

        assert "scheduler_executions" in _table_names(db_path)
        columns = _column_names(db_path)
        for column in (
            "origin",
            "occurrence_id",
            "blocker_task_name",
        ):
            assert column in columns

    def test_init_db_is_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "executions.sqlite"
        init_db(db_path)
        init_db(db_path)  # 不抛错

    def test_add_and_list_round_trip_with_new_fields(self, state: AppState):
        started_at = datetime(2026, 8, 16, 0, 0, 0, tzinfo=UTC)
        execution = TaskExecution(
            id="run-1",
            task_id="task-1",
            task_name="定时任务",
            origin="native",
            occurrence_id="task-1:2026-08-16T01:02:03+00:00",
            blocker_task_name="手动任务",
            started_at=started_at,
            status="running",
            error_message=None,
        )

        add_execution(state.scheduler_db_path, execution)

        rows = list_executions(state.scheduler_db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row.id == "run-1"
        assert row.task_id == "task-1"
        assert row.task_name == "定时任务"
        assert row.origin == "native"
        assert row.occurrence_id == "task-1:2026-08-16T01:02:03+00:00"
        assert row.blocker_task_name == "手动任务"
        assert row.started_at == started_at
        assert row.finished_at is None
        assert row.status == "running"
        assert row.error_message is None

    def test_list_executions_ordered_newest_first(self, state: AppState):
        for index, started in enumerate(
            [
                datetime(2026, 8, 16, 0, 0, 0, tzinfo=UTC),
                datetime(2026, 8, 17, 0, 0, 0, tzinfo=UTC),
                datetime(2026, 8, 18, 0, 0, 0, tzinfo=UTC),
            ]
        ):
            add_execution(
                state.scheduler_db_path,
                TaskExecution(
                    id=f"run-{index}",
                    task_id=None,
                    task_name="手动任务",
                    origin="manual",
                    started_at=started,
                    status="running",
                ),
            )

        rows = list_executions(state.scheduler_db_path)
        assert [row.id for row in rows] == ["run-2", "run-1", "run-0"]

    def test_list_executions_missing_db_returns_empty(self, tmp_path: Path):
        assert list_executions(tmp_path / "nope.sqlite") == []

    def test_finish_execution_updates_status_and_finished_at(self, state: AppState):
        add_execution(
            state.scheduler_db_path,
            TaskExecution(
                id="run-1",
                task_id="task-1",
                task_name="定时任务",
                origin="in_app",
                started_at=datetime(2026, 8, 16, 0, 0, 0, tzinfo=UTC),
                status="running",
            ),
        )

        finish_execution(state.scheduler_db_path, "run-1", "success", error="一切正常")

        row = list_executions(state.scheduler_db_path)[0]
        assert row.status == "success"
        assert row.finished_at is not None
        assert row.error_message == "一切正常"


# ---------------------------------------------------------------------------
# submit_manual — 准入与冲突
# ---------------------------------------------------------------------------


class TestSubmitManual:
    async def test_first_accepted_second_conflicts_busy_manual(self, state: AppState):
        first = await submit_manual(state, make_payload("手动任务A"))
        assert first.accepted is True
        assert first.run_id is not None
        assert first.conflict is None
        assert state.active_run is not None

        second = await submit_manual(state, make_payload("手动任务B"))
        assert second.accepted is False
        assert second.run_id is None
        assert second.conflict is not None
        assert second.conflict.code == "busy_manual"
        assert second.conflict.active_run_id == first.run_id
        assert second.conflict.active_task_name == "手动任务A"
        assert second.conflict.active_origin == "manual"

        # 等待后台协程自然收尾（worker=None → failed）
        await _await_active_task(state)
        assert state.active_run is None
        rows = list_executions(state.scheduler_db_path)
        assert len(rows) == 1
        assert rows[0].id == first.run_id
        assert rows[0].status == "failed"
        assert "Worker 未就绪" in rows[0].error_message

    async def test_success_manual_run_with_fake_worker(self, state: AppState):
        worker = _FakeWorker(start_result=True, ready=True)
        worker.tasks = _FakeSuccessfulTaskService(
            result=True, task_state=worker.task_state
        )
        state.worker = worker

        admission = await submit_manual(state, make_payload("Startup"))
        assert admission.accepted is True
        assert admission.run_id is not None
        assert state.active_run is not None

        await _await_active_task(state)

        # 运行结束后清槽
        assert state.active_run is None
        assert state.active_execution_task is None
        # 成功运行落库 success
        row = list_executions(state.scheduler_db_path)[0]
        assert row.id == admission.run_id
        assert row.status == "success"
        assert row.finished_at is not None
        assert worker.events.terminal_events == [(["Startup"], "Startup", True)]

    async def test_update_in_progress_conflict(self, state: AppState):
        state.update_in_progress = True

        admission = await submit_manual(state, make_payload())

        assert admission.accepted is False
        assert admission.run_id is not None
        assert admission.conflict is not None
        assert admission.conflict.code == "update_in_progress"
        assert state.active_run is None
        assert list_executions(state.scheduler_db_path) == []

    async def test_add_execution_failure_rolls_back_slot(
        self, state: AppState, monkeypatch
    ):
        def _boom(path: Path, execution: TaskExecution):
            raise RuntimeError("disk failure")

        # add_execution 抛错：准入必须回滚 active_run，否则槽位永久占用、后续启动全被拒 busy
        with monkeypatch.context() as m:
            m.setattr("maa_worker.execution.add_execution", _boom)
            with pytest.raises(RuntimeError, match="disk failure"):
                await submit_manual(state, make_payload())

        assert state.active_run is None
        assert state.active_execution_task is None
        assert list_executions(state.scheduler_db_path) == []

        # 槽位未被 wedged：monkeypatch 已撤销，恢复 add_execution 后再次启动可正常准入
        admission = await submit_manual(state, make_payload())
        assert admission.accepted is True
        await _await_active_task(state)
        assert state.active_run is None


# ---------------------------------------------------------------------------
# submit_scheduled — 迟到/忙/更新中
# ---------------------------------------------------------------------------


class TestSubmitScheduled:
    async def test_native_origin_is_accepted(self, state: AppState):
        task = make_task()

        admission = await submit_scheduled(state, task, origin="native")

        assert admission.accepted is True
        assert admission.run_id is not None
        await _await_active_task(state)
        row = list_executions(state.scheduler_db_path)[0]
        assert row.status == "failed"  # worker=None，自然失败收尾

    @pytest.mark.parametrize(
        ("blocker_origin", "expected_status", "blocker_name"),
        [
            ("manual", "skipped_busy_manual", "手动任务A"),
            ("in_app", "skipped_busy_scheduled", "定时任务"),
        ],
    )
    async def test_skipped_busy_while_run_active(
        self,
        state: AppState,
        blocker_origin: str,
        expected_status: str,
        blocker_name: str,
    ):
        # ready worker + 启动成功：首个运行在 running 置回 False 前持续占槽
        worker = _FakeWorker(start_result=True, ready=True)
        # 手动运行的标签取首个任务名，它必须是有效任务，否则首个运行会立即失败清槽
        worker.interface = _FakeInterface(["Startup", blocker_name])
        state.worker = worker

        if blocker_origin == "manual":
            first = await submit_manual(state, make_payload(blocker_name))
        else:
            first = await submit_scheduled(
                state,
                make_task("task-a", name=blocker_name, with_payload=True),
                origin="in_app",
            )
        assert first.accepted is True

        task = make_task()
        admission = await submit_scheduled(state, task, origin="in_app")

        assert admission.accepted is False
        assert admission.skip_status == expected_status
        assert admission.run_id is not None
        skip = {row.id: row for row in list_executions(state.scheduler_db_path)}[
            admission.run_id
        ]
        assert skip.status == expected_status
        assert skip.task_id == task.id
        assert skip.origin == "in_app"
        assert skip.blocker_task_name == blocker_name
        # 必须等任务真正启动后再结束：前置任务在线程池中执行，过早置 running=False
        # 会被随后的 start() 覆盖，运行协程将永远轮询下去
        for _ in range(500):
            if worker.task_state.running:
                break
            await asyncio.sleep(0.01)
        assert worker.task_state.running
        # 结束任务（last_status 默认非 success → failed），清槽
        worker.task_state.running = False
        await _await_active_task(state)
        assert state.active_run is None

    async def test_skipped_update_in_progress(self, state: AppState):
        state.update_in_progress = True
        task = make_task()

        admission = await submit_scheduled(state, task, origin="in_app")

        assert admission.accepted is False
        assert admission.skip_status == "skipped_update_in_progress"
        row = list_executions(state.scheduler_db_path)[0]
        assert row.status == "skipped_update_in_progress"


# ---------------------------------------------------------------------------
# PI pretask admission
# ---------------------------------------------------------------------------


class TestPretaskAdmission:
    async def test_pretask_failure_records_failed_and_terminal_event(
        self, state: AppState
    ):
        worker = _FakeWorker(start_result=True, ready=True)
        worker.pretasks.error = PretaskError("pretask failed")
        state.worker = worker

        admission = await submit_manual(state, make_payload())
        assert admission.accepted is True
        await _await_active_task(state)

        assert worker.tasks.called is False
        row = list_executions(state.scheduler_db_path)[0]
        assert row.id == admission.run_id
        assert row.status == "failed"
        assert row.error_message == "pretask failed"
        assert len(worker.events.failed_events) == 1
        assert "任务异常详情: pretask failed" in worker.events.logs

    async def test_pretask_stopped_records_stopped_and_terminal_event(
        self, state: AppState
    ):
        worker = _FakeWorker(start_result=True, ready=True)
        worker.pretasks.error = PretaskStopped("pretask stopped")
        # A real stop request sets stop_flag while the pretask is running; this
        # makes the fake raise through the same classification path.
        worker.pretasks.set_stop_flag_on_error = True
        state.worker = worker

        admission = await submit_manual(state, make_payload())
        assert admission.accepted is True
        await _await_active_task(state)

        row = list_executions(state.scheduler_db_path)[0]
        assert row.id == admission.run_id
        assert row.status == "stopped"
        assert row.error_message == "任务已终止"
        assert len(worker.events.failed_events) == 1

    async def test_empty_task_list_fails_before_pretask_side_effects(
        self, state: AppState
    ):
        # 载荷中的任务在接口中不存在：规范化后任务列表为空，
        # 必须先失败，不得执行任何前置命令。
        worker = _FakeWorker(start_result=True, ready=True)
        state.worker = worker

        payload = make_payload("RemovedTask")
        admission = await submit_manual(state, payload)
        assert admission.accepted is True
        await _await_active_task(state)

        assert worker.pretasks.calls == []
        assert worker.tasks.called is False
        row = list_executions(state.scheduler_db_path)[0]
        assert row.id == admission.run_id
        assert row.status == "failed"
        assert row.error_message == "任务列表为空"

    async def test_checkbox_below_min_count_fails_before_pretasks(
        self, state: AppState
    ):
        # 省略 default_case 的 min_count 选项可以加载和保存，但不得以不足的选择启动
        worker = _FakeWorker(start_result=True, ready=True)
        worker.interface.task = [
            SimpleNamespace(name="Startup", entry="EntryStartup", option=["mods"])
        ]
        worker.interface.option = {
            "mods": Option(
                type="checkbox",
                cases=[OptionCase(name="a"), OptionCase(name="b")],
                min_count=1,
            )
        }
        state.worker = worker

        admission = await submit_manual(state, make_payload())
        assert admission.accepted is True
        await _await_active_task(state)

        assert worker.pretasks.calls == []
        assert worker.tasks.called is False
        row = list_executions(state.scheduler_db_path)[0]
        assert row.status == "failed"
        assert "mods" in row.error_message

    async def test_previous_stop_does_not_block_next_run(self, state: AppState):
        # 上一次运行被停止后 stop_flag 遗留为 True；新运行占槽时必须复位，
        # 否则前置任务和 TaskService.start() 会把它当作本次的停止请求。
        worker = _FakeWorker(start_result=True, ready=True)
        worker.tasks = _FakeSuccessfulTaskService(
            result=True, task_state=worker.task_state
        )
        worker.task_state.stop_flag = True
        state.worker = worker

        admission = await submit_manual(state, make_payload())
        assert admission.accepted is True
        await _await_active_task(state)

        assert worker.pretasks.stop_flags == [False]
        assert worker.tasks.called is True
        assert list_executions(state.scheduler_db_path)[0].status == "success"

    async def test_pretask_receives_normalized_pre_tasks(self, state: AppState):
        # pretask 使用规范化后的前置命令（剔除禁用与空命令）。
        worker = _FakeWorker(start_result=True, ready=True)
        worker.tasks = _FakeSuccessfulTaskService(
            result=True, task_state=worker.task_state
        )
        state.worker = worker

        payload = make_payload()
        payload.preTasks = [
            PreTaskCommand(command="echo ok"),
            PreTaskCommand(command="disabled", enabled=False),
        ]
        admission = await submit_manual(state, payload)
        assert admission.accepted is True
        await _await_active_task(state)

        controller, resource, pre_tasks, option_values = worker.pretasks.calls[0]
        assert (controller, resource) == ("AdbController", "main")
        assert [p.command for p in pre_tasks] == ["echo ok"]
        assert option_values == {}

    async def test_global_option_values_reach_pretask_and_task_pipeline_separately(
        self, state: AppState
    ):
        worker = _FakeWorker(start_result=True, ready=True)
        worker.tasks = _FakeSuccessfulTaskService(
            result=True, task_state=worker.task_state
        )
        worker.interface.task = [
            SimpleNamespace(name="Startup", entry="EntryStartup", option=[]),
            SimpleNamespace(name="Second", entry="EntrySecond", option=[]),
        ]
        worker.interface.option = {
            "global_setting": Option(
                type="select",
                cases=[OptionCase(name="default"), OptionCase(name="from-settings")],
                default_case="default",
            )
        }
        worker.interface.global_option = ["global_setting"]
        state.settings = SettingsModel(
            globalOptionValues={"global_setting": "from-settings"}
        )
        state.worker = worker

        payload = make_payload()
        payload.task_list = ["Startup", "Second"]
        admission = await submit_manual(state, payload)
        assert admission.accepted is True
        await _await_active_task(state)

        assert len(worker.pretasks.calls) == 1
        assert worker.pretasks.calls[0][3] == {"global_setting": "from-settings"}
        assert worker.tasks.global_options == {"global_setting": "from-settings"}

    async def test_pretask_runs_before_device_connection(
        self, state: AppState, monkeypatch
    ):
        settings = SimpleNamespace(
            runtime=SimpleNamespace(autoRetry=True, maxRetryCount=1, retryInterval=0)
        )
        monkeypatch.setattr("maa_worker.execution.load_settings", lambda: settings)
        ordering: list[str] = []
        worker = _FakeWorker(start_result=True, ordering=ordering)
        worker.tasks = _FakeSuccessfulTaskService(
            result=True, task_state=worker.task_state
        )
        state.worker = worker

        admission = await submit_manual(state, make_payload())
        assert admission.accepted is True
        await _await_active_task(state)

        assert ordering == ["pretask", "connect"]
        row = list_executions(state.scheduler_db_path)[0]
        assert row.id == admission.run_id
        assert row.status == "success"


# ---------------------------------------------------------------------------
# stop_active / 取消清理
# ---------------------------------------------------------------------------


class TestStopAndCancel:
    async def test_stop_active_without_active_returns_false(self, state: AppState):
        assert await stop_active(state) is False

    async def test_cancel_active_clears_slot_and_marks_stopped(self, state: AppState):
        admission = await submit_manual(state, make_payload())
        assert state.active_run is not None

        task = state.active_execution_task
        assert task is not None
        task.cancel()
        # 清槽在 done_callback 中同步完成；补记落库经 asyncio.to_thread 异步执行，轮询等待
        for _ in range(100):
            if state.active_run is None:
                break
            await asyncio.sleep(0.01)

        assert state.active_run is None
        assert state.active_execution_task is None
        row = None
        for _ in range(100):
            rows = list_executions(state.scheduler_db_path)
            if rows and rows[0].status == "stopped":
                row = rows[0]
                break
            await asyncio.sleep(0.01)
        assert row is not None
        assert row.id == admission.run_id
        assert row.status == "stopped"
        assert "取消" in row.error_message

    async def test_prestart_failure_emits_terminal_event(self, state: AppState):
        state.worker = _FakeWorker(start_result=False, ready=True)

        admission = await submit_manual(state, make_payload())
        assert admission.accepted is True

        task = state.active_execution_task
        assert task is not None
        await task

        # run_process 未启动（tasks.start 返回 False）：必须补发 task.failed 终端事件，
        # 否则前端 TaskRunning 在 accept 后被置位却无清除事件，UI 卡死。
        assert state.active_run is None
        assert state.worker.events.failed_events, (
            "expected emit_task_failed for pre-start failure"
        )
        row = list_executions(state.scheduler_db_path)[0]
        assert row.status == "failed"

    async def test_stop_during_prestart_cancels_and_clears_slot(
        self, state: AppState, monkeypatch
    ):
        # 强制设备连接阶段阻塞在准备阶段，使停止请求发生时任务尚未真正启动
        settings = SimpleNamespace(
            runtime=SimpleNamespace(autoRetry=True, maxRetryCount=1, retryInterval=0)
        )
        monkeypatch.setattr("maa_worker.execution.load_settings", lambda: settings)
        worker = _FakeWorker(start_result=True, block_connect=True)
        state.worker = worker

        admission = await submit_manual(state, make_payload())
        assert admission.accepted is True

        # 让后台协程进入 device.connect 阻塞等待
        for _ in range(20):
            if worker.device.connect_called:
                break
            await asyncio.sleep(0.01)
        assert worker.device.connect_called is True

        assert await stop_active(state) is True
        worker.device.release.set()

        task = state.active_execution_task
        assert task is not None
        await asyncio.gather(task, return_exceptions=True)

        # 任务从未真正启动：tasks.start 未被调用，槽位已清，落库为 stopped
        assert worker.tasks.called is False
        assert state.active_run is None
        assert state.active_execution_task is None
        assert len(worker.events.failed_events) == 1
        row = list_executions(state.scheduler_db_path)[0]
        assert row.id == admission.run_id
        assert row.status == "stopped"

    async def test_cancel_during_pretask_holds_slot_until_thread_exits(
        self, state: AppState
    ):
        # 停止发生在前置线程两条命令之间（尚无子进程可终止）：槽位必须保持到线程退出，
        # 否则新运行复位共享 stop_flag 后，旧线程会继续执行下一条前置命令。
        worker = _FakeWorker(start_result=True)
        entered = threading.Event()
        release = threading.Event()
        observed_stop_flag: list[bool] = []

        def blocking_run_all(*args, **kwargs):
            entered.set()
            release.wait(timeout=5)
            observed_stop_flag.append(worker.task_state.stop_flag)

        worker.pretasks.run_all = blocking_run_all
        state.worker = worker

        await submit_manual(state, make_payload())
        assert await asyncio.to_thread(entered.wait, 5)

        task = state.active_execution_task
        assert task is not None
        task.cancel()
        await asyncio.sleep(0.1)

        assert not task.done()
        assert state.active_run is not None
        assert (await submit_manual(state, make_payload())).accepted is False

        release.set()
        await asyncio.gather(task, return_exceptions=True)

        assert observed_stop_flag == [True]
        assert state.active_run is None
        assert worker.tasks.called is False


class TestTerminalEventOrdering:
    async def test_terminal_event_published_after_slot_cleared(self, state: AppState):
        # 前端收到 task.completed 后会立刻发起新一轮启动，此时槽位必须已清空，
        # 否则新启动会被 busy_manual 拒绝。
        worker = _FakeWorker(start_result=True, ready=True)
        worker.tasks = _FakeSuccessfulTaskService(
            result=True, task_state=worker.task_state
        )
        slot_free_at_emit: list[bool] = []
        record = worker.events.publish_task_terminal

        def publish(*args):
            slot_free_at_emit.append(state.active_run is None)
            return record(*args)

        worker.events.publish_task_terminal = publish
        state.worker = worker

        admission = await submit_manual(state, make_payload())
        assert admission.accepted is True
        await _await_active_task(state)

        assert slot_free_at_emit == [True]
        assert list_executions(state.scheduler_db_path)[0].status == "success"

    async def test_scheduled_terminal_event_uses_schedule_name(self, state: AppState):
        worker = _FakeWorker(start_result=True, ready=True)
        worker.tasks = _FakeSuccessfulTaskService(
            result=True, task_state=worker.task_state
        )
        state.worker = worker

        task = make_task(name="每日例行", with_payload=True)
        admission = await submit_scheduled(state, task, origin="in_app")
        assert admission.accepted is True
        await _await_active_task(state)

        assert worker.events.terminal_events == [(["Startup"], "每日例行", True)]


@pytest.mark.parametrize(
    ("auto_retry", "expected_connect_calls"),
    [(False, 1), (True, 3)],
)
async def test_connect_attempts_follow_auto_retry_setting(
    state: AppState,
    monkeypatch,
    auto_retry: bool,
    expected_connect_calls: int,
):
    settings = SimpleNamespace(
        runtime=SimpleNamespace(autoRetry=auto_retry, maxRetryCount=3, retryInterval=0)
    )
    monkeypatch.setattr("maa_worker.execution.load_settings", lambda: settings)
    worker = _FakeWorker(start_result=True, block_connect=True)
    worker.device.fail_connect = True
    worker.device.release.set()
    state.worker = worker

    admission = await submit_manual(state, make_payload())
    assert admission.accepted is True
    await _await_active_task(state)

    assert worker.device.connect_calls == expected_connect_calls
    assert list_executions(state.scheduler_db_path)[0].status == "failed"
