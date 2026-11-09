import threading
import time
from typing import TYPE_CHECKING

import plyer

from backend.core.settings_io import default_settings_path, load_settings_model
from backend.models.api import RealtimeEvent, RealtimeEventLevel, RealtimeEventName
from backend.models.settings import Notification, NotificationTrigger, SettingsModel
from backend.services.notification import send_external

if TYPE_CHECKING:
    from backend.maa_worker.worker import MaaWorker


def current_time() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def load_settings() -> SettingsModel:
    return load_settings_model(default_settings_path())


class EventService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def _publish_event(self, event: RealtimeEvent):
        self.worker.message_conn.put(event)
        time.sleep(0.05)

    def _show_system_notification(self, title: str, message: str):
        notifier = plyer.notification
        if notifier is None:
            raise RuntimeError("当前平台不支持系统通知")

        notify_func = getattr(notifier, "notify", None)
        if notify_func is None:
            raise RuntimeError("当前平台不支持系统通知")

        notify_func(
            title=title,
            message=message,
            app_name=self.worker.text.app_name(),
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
        )

        self._publish_event(realtime_event)
        self.deliver_notification(realtime_event)

    def deliver_notification(self, event: RealtimeEvent):
        """按设置发送系统/外部通知；外部渠道在守护线程发送，sink 回调与停止不等待网络。"""
        if "notification" not in event.notify:
            return

        title = event.title or self.worker.text.app_name()
        message = event.message
        settings = load_settings()

        if settings.notification.systemNotification:
            try:
                self._show_system_notification(title, message)
            except Exception as exc:
                self.send_log(f"系统通知发送失败: {exc}")

        if settings.notification.externalNotification:
            threading.Thread(
                target=self._send_external,
                args=(settings.notification, title, message, event.level),
                daemon=True,
            ).start()

    def _send_external(
        self,
        notification: Notification,
        title: str,
        message: str,
        level: RealtimeEventLevel,
    ) -> None:
        # 截图在发送线程里取，调用方（sink 回调、收尾）不等设备
        screenshot = (
            self.worker.capture_notification_jpeg()
            if notification.attachScreenshot
            else None
        )
        for error in send_external(
            notification.channels, title, message, level, screenshot
        ):
            self.send_log(f"外部通知发送失败: {error}")

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

    def notify(
        self,
        trigger: NotificationTrigger,
        title: str,
        message: str,
        *,
        event: RealtimeEventName = "notification",
        level: RealtimeEventLevel = "info",
    ):
        """按触发时机开关决定是否推送通知；关闭时事件仍照常进入日志。"""
        enabled = getattr(load_settings().notification, trigger)
        self.emit(
            event,
            message,
            level=level,
            notify=["notification"] if enabled else [],
            title=title,
        )

    def _build_task_subject(self, task_list: list[str]) -> str:
        if self.worker.task_state.current_task_name:
            return self.worker.task_state.current_task_name
        if len(task_list) == 1:
            return task_list[0]
        return f"{len(task_list)} 个任务"

    def emit_task_started(self, task_list: list[str]):
        self.notify(
            "notifyOnStart",
            "任务开始",
            f"开始执行: {self._build_task_subject(task_list)}",
            event="task.started",
        )

    def publish_task_terminal(
        self,
        task_list: list[str],
        run_label: str | None,
        succeeded: bool,
        settings: SettingsModel,
    ) -> RealtimeEvent:
        """同步入队 task.completed / task.failed，不走节流 sleep。

        调用方在事件循环中与清槽处于同一同步段，保证新运行的 task.started
        不会排在旧运行的终端事件之前；settings 由调用方预先在线程中读取。
        通知等慢操作由 deliver_notification 另行处理。
        """
        subject = run_label or self._build_task_subject(task_list)
        if succeeded:
            notify = ["notification"] if settings.notification.notifyOnComplete else []
            event = RealtimeEvent(
                event="task.completed",
                level="success",
                message=f"{subject} 执行完成",
                time=current_time(),
                notify=notify,
                title="任务完成",
            )
        else:
            notify = ["notification"] if settings.notification.notifyOnError else []
            event = RealtimeEvent(
                event="task.failed",
                level="error",
                message=f"{subject} 执行失败，请检查日志",
                time=current_time(),
                notify=notify,
                title="任务失败",
            )
        self.worker.message_conn.put(event)
        return event
