import base64
import hashlib
import json
from queue import SimpleQueue
from types import SimpleNamespace
from typing import Any, cast

import pytest

from backend.maa_worker.event_service import EventService
from backend.models.notification import WebhookChannel, WeComChannel
from backend.models.settings import Notification, SettingsModel
from backend.services import notification as notification_module
from backend.services.notification import send_external

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


class _Response:
    def __init__(self, body: dict[str, Any]):
        self._body = body
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._body


@pytest.mark.parametrize(
    ("enabled", "expected"), [(True, ["notification"]), (False, [])]
)
def test_trigger_switch_gates_push_but_keeps_log(monkeypatch, enabled, expected):
    settings = SettingsModel(notification=Notification(notifyOnConnectFailed=enabled))
    monkeypatch.setattr(
        "backend.maa_worker.event_service.load_settings", lambda: settings
    )
    worker = SimpleNamespace(message_conn=SimpleQueue())
    events = EventService(cast(Any, worker))

    events.notify(
        "notifyOnConnectFailed", "设备连接失败", "adb: timeout", level="error"
    )

    event = worker.message_conn.get_nowait()
    assert event.notify == expected
    assert event.message == "adb: timeout"
    assert event.display is True


def test_wecom_sends_screenshot_after_text(monkeypatch):
    posts: list[dict[str, Any]] = []

    def post(_url, **kwargs):
        posts.append(kwargs["json"])
        return _Response({"errcode": 0})

    monkeypatch.setattr(notification_module.requests, "post", post)
    channel = WeComChannel(id="w", type="wecom", params={"key": "k"})

    assert send_external([channel], "任务失败", "Daily 执行失败", "error", JPEG) == []

    assert [payload["msgtype"] for payload in posts] == ["text", "image"]
    assert posts[1]["image"] == {
        "base64": base64.b64encode(JPEG).decode(),
        "md5": hashlib.md5(JPEG).hexdigest(),
    }


def test_wecom_without_screenshot_sends_text_only(monkeypatch):
    posts: list[dict[str, Any]] = []

    def post(_url, **kwargs):
        posts.append(kwargs["json"])
        return _Response({"errcode": 0})

    monkeypatch.setattr(notification_module.requests, "post", post)
    channel = WeComChannel(id="w", type="wecom", params={"key": "k"})

    assert send_external([channel], "任务完成", "Daily 执行完成", "success") == []
    assert [payload["msgtype"] for payload in posts] == ["text"]


@pytest.mark.parametrize(
    ("screenshot", "expected"), [(JPEG, base64.b64encode(JPEG).decode()), (None, "")]
)
def test_webhook_screenshot_placeholder(monkeypatch, screenshot, expected):
    sent: list[dict[str, Any]] = []

    def request(_method, _url, **kwargs):
        sent.append(kwargs["json"])
        return _Response({})

    monkeypatch.setattr(notification_module.requests, "request", request)
    channel = WebhookChannel(
        id="h",
        type="webhook",
        params={
            "url": "https://example.invalid/hook",
            "body": json.dumps({"text": "{{message}}", "image": "{{screenshot}}"}),
        },
    )

    assert send_external([channel], "t", "m", "info", screenshot) == []
    assert sent == [{"text": "m", "image": expected}]
