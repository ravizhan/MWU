"""Tests for task lifecycle event context."""

from queue import SimpleQueue
from types import SimpleNamespace

from maa_worker.event_service import EventService


class _Worker:
    def __init__(self, run_id: str | None):
        self.message_conn = SimpleQueue()
        self.interface = SimpleNamespace(label="Test")
        self.task_state = SimpleNamespace(current_task_name=None)
        self.state = SimpleNamespace(
            active_run=(SimpleNamespace(run_id=run_id) if run_id else None)
        )


def test_task_started_includes_active_run_id(monkeypatch):
    worker = _Worker("run-123")
    monkeypatch.setattr(
        "maa_worker.event_service.load_settings",
        lambda: SimpleNamespace(
            notification=SimpleNamespace(
                systemNotification=False,
                externalNotification=False,
            )
        ),
    )

    EventService(worker).emit_task_started(["Startup"])

    event = worker.message_conn.get()
    assert event.event == "task.started"
    assert event.details == {"run_id": "run-123"}
