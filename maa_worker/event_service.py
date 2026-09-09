import time
from typing import TYPE_CHECKING, Any

import plyer

import json_utils as json
from models.api import RealtimeEvent, RealtimeEventLevel, RealtimeEventName
from models.settings import SettingsModel
from settings_io import default_settings_path, load_settings_model

if TYPE_CHECKING:
    from maa_utils import MaaWorker


def current_time() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def load_settings() -> SettingsModel:
    try:
        return load_settings_model(default_settings_path())
    except Exception:
        return SettingsModel()


class EventService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def _publish_event(self, event: RealtimeEvent):
        self.worker.message_conn.put(event)
        time.sleep(0.05)

    def show_system_notification(self, title: str, message: str):
        notifier = plyer.notification
        if notifier is None:
            raise RuntimeError("当前平台不支持系统通知")

        notify_func = getattr(notifier, "notify", None)
        if notify_func is None:
            raise RuntimeError("当前平台不支持系统通知")

        notify_func(
            title=title,
            message=message,
            app_name=self.worker.interface.label,
            timeout=30,
        )

    def emit(
        self,
        event: RealtimeEventName,
        message: str,
        *,
        level: RealtimeEventLevel = "info",
        notify: list[str] | None = None,
        title: str | None = None,
        display: bool = True,
        details: dict[str, Any] | None = None,
    ):
        notify = notify or []
        realtime_event = RealtimeEvent(
            event=event,
            level=level,
            message=message,
            time=current_time(),
            notify=notify,
            title=title,
            display=display,
            details=details,
        )

        self._publish_event(realtime_event)

        if "notification" not in notify:
            return

        settings = load_settings()

        if settings.notification.systemNotification:
            try:
                self.show_system_notification(
                    title or self.worker.interface.label or "MWU", message
                )
            except Exception as exc:
                self.send_log(f"系统通知发送失败: {exc}")

        if settings.notification.externalNotification:
            try:
                template_body = settings.notification.body.strip()
                if template_body:
                    body = json.loads(
                        template_body.replace("{{title}}", title or "").replace(
                            "{{message}}", message
                        )
                    )
                else:
                    body = {
                        "title": title or self.worker.interface.label,
                        "message": message,
                    }

                headers = {}
                if settings.notification.headers:
                    headers = json.loads(settings.notification.headers)

                auth = None
                if settings.notification.username and settings.notification.password:
                    auth = (
                        settings.notification.username,
                        settings.notification.password,
                    )

                if settings.notification.method == "POST":
                    if settings.notification.contentType == "application/json":
                        if auth is not None:
                            self.worker.http_client.post(
                                settings.notification.webhook,
                                headers=headers,
                                json=body,
                                auth=auth,
                            )
                        else:
                            self.worker.http_client.post(
                                settings.notification.webhook,
                                headers=headers,
                                json=body,
                            )
                    else:
                        if auth is not None:
                            self.worker.http_client.post(
                                settings.notification.webhook,
                                headers=headers,
                                data=body,
                                auth=auth,
                            )
                        else:
                            self.worker.http_client.post(
                                settings.notification.webhook,
                                headers=headers,
                                data=body,
                            )
                else:
                    self.worker.http_client.get(
                        settings.notification.webhook, params=body
                    )
            except Exception as exc:
                self.send_log(f"外部通知发送失败: {exc}")

    def send_log(self, msg: str):
        self.emit("log", msg)

    def send_notification(
        self,
        title: str,
        message: str,
        *,
        event: RealtimeEventName = "notification.test",
        level: RealtimeEventLevel = "info",
        notify: list[str] | None = None,
    ):
        self.emit(
            event, message, level=level, notify=notify or ["notification"], title=title
        )

    def _build_task_subject(self, task_list: list[str]) -> str:
        if self.worker.task_state.current_task_name:
            return self.worker.task_state.current_task_name
        if len(task_list) == 1:
            return task_list[0]
        return f"{len(task_list)} 个任务"

    def emit_task_started(self, task_list: list[str]):
        self.send_notification(
            "任务开始",
            f"开始执行: {self._build_task_subject(task_list)}",
            event="task.started",
            level="info",
        )

    def emit_task_completed(self, task_list: list[str]):
        settings = load_settings()
        self.emit(
            "task.completed",
            f"{self._build_task_subject(task_list)} 执行完成",
            level="success",
            notify=["notification"] if settings.notification.notifyOnComplete else [],
            title="任务完成",
        )

    def emit_task_failed(self, task_list: list[str], error_message: str):
        settings = load_settings()
        self.emit(
            "task.failed",
            f"{self._build_task_subject(task_list)} 执行失败，请检查日志",
            level="error",
            notify=["notification"] if settings.notification.notifyOnError else [],
            title="任务失败",
        )
        self.send_log(f"任务异常详情: {error_message}")
