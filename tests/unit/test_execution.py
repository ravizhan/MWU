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
        task_identity="name",
        task_list=[task_name],
        controller_name="AdbController",
        device=ScheduledTaskDeviceConfig(
            controller_name="AdbController",
            device_type="Adb",
            device_address="127.0.0.1:5555",
        ),
        resource_name="main",
    )


def make_task(task_id: str = "task-1", name: str = "定时任务") -> ScheduledTask:
    return ScheduledTask(
        task_identity="name",
        id=task_id,
        name=name,
        wakeup_enabled=True,
        enabled=True,
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
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
        self.failed_events: list[tuple[list[str], str]] = []
        self.logs: list[str] = []

    def send_log(self, msg: str):
        self.logs.append(msg)

    def emit_task_failed(self, task_list: list[str], error_message: str):
        self.failed_events.append((list(task_list), error_message))


class _FakeInterface:
    def __init__(self, entries: list[str]):
        self.task = [SimpleNamespace(name=e, entry=e, option=[]) for e in entries]
        self.option = {}
        self.global_option = []
        self.pretask = []
        self.resource = []
        self.controller = []
        self.setting = []


class _FakeTaskService:
    def __init__(self, result: bool, task_state: "_FakeTaskState | None" = None):
        self.result = result
        self.called = False
        self.block: threading.Event | None = None
        self._task_state = task_state
        self.global_options = {}

    def start(
        self,
        task_list,
        options,
        task_name=None,
        pre_tasks=None,
        global_options=None,
    ):
        self.called = True
        self.global_options = global_options or {}
        if self.block is not None:
            # 阻塞至测试放行，模拟任务长时间占槽
            self.block.wait(timeout=5)
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
        global_options=None,
    ):
        self.calls.append(
            (
                controller_name,
                resource_name,
                user_pre_tasks,
                global_options or {},
            )
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
    prepared_resource_name: str | None = None
    last_device_error: str | None = None


class _FakeDevice:
    """模拟慢速设备连接（connect 阻塞至 release 事件，供停止测试在准备阶段取消）。"""

    def __init__(self, *, ordering: list[str] | None = None, block: bool = True):
        self.release = threading.Event()
        if not block:
            self.release.set()
        self.connect_called = False
        self.prepare_called = False
        self._ordering = ordering
        self._pretasks = None

    def build_device_model_from_config(self, controller_name, device_type, address):
        return SimpleNamespace(
            controller_name=controller_name,
            device_type=device_type,
            device_address=address,
        )

    def connect(self, model):
        self.connect_called = True
        if self._ordering is not None:
            self._ordering.append("connect")
        self.release.wait(timeout=5)
        return True

    def set_resource(self, name):
        return True

    def has_preparation_programs(self, controller_name, resource_name, user_pre_tasks):
        return False

    def prepare_connection(
        self,
        device_config,
        resource_name,
        global_options,
        user_pre_tasks,
    ):
        self.prepare_called = True
        # 与真实服务一致：先执行 pretask 阶段（fake pretasks 内部抛错/记录）
        if self._pretasks is not None:
            self._pretasks.run_all(
                device_config.controller_name,
                resource_name,
                user_pre_tasks,
                global_options=global_options,
            )
        # 复用判定由 _FakeDeviceState 类属性模拟：ready 连接直接复用
        return True


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
        self.interface = _FakeInterface(["Startup", "手动任务A", "手动任务B"])
        self.task_state = _FakeTaskState()
        self.pretasks = _FakePretaskService(self.task_state, ordering)
        self.tasks = _FakeTaskService(start_result, task_state=self.task_state)
        self.device_state = _FakeDeviceState()
        self.device = _FakeDevice(ordering=ordering, block=block_connect)
        self.device._pretasks = self.pretasks
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
        assert "blocker_run_id" not in columns

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

        class _SuccessTaskService(_FakeTaskService):
            def start(
                self,
                task_list,
                options,
                task_name=None,
                pre_tasks=None,
                global_options=None,
            ):
                self.called = True
                self.global_options = global_options or {}
                # 模拟一次成功的手动运行：start 内部完成整个生命周期
                self._task_state.running = True
                self._task_state.last_status = "success"
                self._task_state.running = False
                return True

        worker.tasks = _SuccessTaskService(result=True, task_state=worker.task_state)
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
        assert worker.events.failed_events == []

    async def test_update_in_progress_conflict(self, state: AppState):
        state.update_in_progress = True

        admission = await submit_manual(state, make_payload())

        assert admission.accepted is False
        assert admission.run_id is not None
        assert admission.conflict is not None
        assert admission.conflict.code == "update_in_progress"
        assert state.active_run is None
        assert list_executions(state.scheduler_db_path) == []

    async def test_stop_active_with_active_run_returns_true(self, state: AppState):
        await submit_manual(state, make_payload())
        assert await stop_active(state) is True
        assert state.active_run is not None
        task = state.active_execution_task
        assert task is not None
        await asyncio.gather(task, return_exceptions=True)
        assert state.active_run is None

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

    async def test_skipped_busy_manual_while_manual_run_active(self, state: AppState):
        # ready worker + 阻塞的 start：首个手动任务持续占槽，跳过判定不受清槽时序影响
        worker = _FakeWorker(start_result=True, ready=True)
        worker.tasks.block = threading.Event()
        state.worker = worker

        task = make_task()
        first = await submit_manual(state, make_payload("手动任务A"))
        assert first.accepted is True

        admission = await submit_scheduled(state, task, origin="in_app")

        assert admission.accepted is False
        assert admission.skip_status == "skipped_busy_manual"
        assert admission.run_id is not None
        rows = list_executions(state.scheduler_db_path)
        by_id = {row.id: row for row in rows}
        skip = by_id[admission.run_id]
        assert skip.status == "skipped_busy_manual"
        assert skip.task_id == task.id
        assert skip.origin == "in_app"
        assert skip.blocker_task_name == "手动任务A"
        # 放行 start 并结束任务（last_status 默认非 success → failed），清槽
        worker.tasks.block.set()
        worker.task_state.running = False
        await _await_active_task(state)
        assert state.active_run is None

    async def test_skipped_busy_scheduled_while_scheduled_run_active(
        self, state: AppState
    ):
        worker = _FakeWorker(start_result=True, ready=True)
        worker.tasks.block = threading.Event()
        state.worker = worker

        first = await submit_scheduled(
            state, make_task("task-a", name="定时任务"), origin="in_app"
        )
        assert first.accepted is True

        admission = await submit_scheduled(state, make_task("task-b"), origin="in_app")

        assert admission.accepted is False
        assert admission.skip_status == "skipped_busy_scheduled"
        # 冲突在另一调度运行尚占槽时被检测：跳过记录捕获其任务名
        rows = list_executions(state.scheduler_db_path)
        by_id = {row.id: row for row in rows}
        assert by_id[admission.run_id].status == "skipped_busy_scheduled"
        assert by_id[admission.run_id].blocker_task_name == "定时任务"
        # 放行 start 并结束首个任务，清槽
        worker.tasks.block.set()
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

        assert worker.pretasks.calls == [("AdbController", "main", [], {})]
        assert worker.tasks.called is False
        row = list_executions(state.scheduler_db_path)[0]
        assert row.id == admission.run_id
        assert row.status == "failed"
        assert row.error_message == "pretask failed"
        assert worker.events.failed_events == [(["Startup"], "pretask failed")]

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
        assert worker.events.failed_events == [(["Startup"], "任务已终止")]

    async def test_empty_task_list_fails_before_pretask_side_effects(
        self, state: AppState
    ):
        # 载荷中的任务在接口中不存在：规范化后任务列表为空，
        # 必须先失败，不得执行任何前置命令。
        worker = _FakeWorker(start_result=True, ready=True)
        state.worker = worker

        payload = make_payload("RemovedTask")
        admission = await submit_manual(state, payload)

        # 未知任务名在准入前即被拒绝（HTTP 层映射 422），不占槽、无落库
        assert admission.accepted is False
        assert admission.invalid_task_names == ["RemovedTask"]
        assert admission.run_id is None
        assert state.active_run is None
        assert list_executions(state.scheduler_db_path) == []

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

        controller, resource, pre_tasks, global_options = worker.pretasks.calls[0]
        assert (controller, resource) == ("AdbController", "main")
        assert [p.command for p in pre_tasks] == ["echo ok"]
        assert global_options == {}

    async def test_global_option_values_reach_pretask_and_task_pipeline_separately(
        self, state: AppState
    ):
        worker = _FakeWorker(start_result=True, ready=True)
        worker.tasks = _FakeSuccessfulTaskService(
            result=True, task_state=worker.task_state
        )
        worker.interface.task = [
            SimpleNamespace(name="Startup", entry="Startup", option=[]),
            SimpleNamespace(name="Second", entry="Second", option=[]),
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
            runtime=SimpleNamespace(maxRetryCount=1, retryInterval=0)
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

        assert worker.pretasks.calls == [("AdbController", "main", [], {})]
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
        assert "任务启动失败" in state.worker.events.failed_events[-1][1]
        row = list_executions(state.scheduler_db_path)[0]
        assert row.status == "failed"

    async def test_stop_during_prestart_cancels_and_clears_slot(
        self, state: AppState, monkeypatch
    ):
        # 强制设备连接阶段阻塞在准备阶段，使停止请求发生时任务尚未真正启动
        settings = SimpleNamespace(
            runtime=SimpleNamespace(maxRetryCount=1, retryInterval=0)
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
        row = list_executions(state.scheduler_db_path)[0]
        assert row.id == admission.run_id
        assert row.status == "stopped"
