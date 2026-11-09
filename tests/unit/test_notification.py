import base64
import hashlib
import io
import json
import random
from queue import SimpleQueue
from types import SimpleNamespace
from typing import Any, cast

import numpy
import pytest
from PIL import Image

from backend.maa_worker import event_service as event_module
from backend.maa_worker.event_service import EventService
from backend.maa_worker.worker import MaaWorker
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


class _InlineThread:
    """让外部通知的发送线程在 start() 里同步跑完，测试结束前就能看到请求。"""

    def __init__(self, target, args, daemon):
        self._target = target
        self._args = args

    def start(self) -> None:
        self._target(*self._args)


def _webhook(body: str = "") -> WebhookChannel:
    return WebhookChannel(
        id="h",
        type="webhook",
        params={"url": "https://example.invalid/hook", "body": body},
    )


def _capture_requests(monkeypatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def request(_method, _url, **kwargs):
        sent.append(kwargs["json"])
        return _Response({})

    monkeypatch.setattr(notification_module.requests, "request", request)
    return sent


@pytest.mark.parametrize("enabled", [True, False])
def test_trigger_switch_gates_push_but_keeps_log(monkeypatch, enabled):
    settings = SettingsModel(
        notification=Notification(
            externalNotification=True,
            channels=[_webhook()],
            notifyOnConnectFailed=enabled,
        )
    )
    monkeypatch.setattr(event_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        event_module, "threading", SimpleNamespace(Thread=_InlineThread)
    )
    sent = _capture_requests(monkeypatch)
    worker = SimpleNamespace(message_conn=SimpleQueue())
    events = EventService(cast(Any, worker))

    events.notify(
        "notifyOnConnectFailed", "设备连接失败", "adb: timeout", level="error"
    )

    event = worker.message_conn.get_nowait()
    assert event.message == "adb: timeout"
    assert event.display is True
    expected = [{"title": "设备连接失败", "message": "adb: timeout"}]
    assert sent == (expected if enabled else [])


@pytest.mark.parametrize(
    "job",
    [
        SimpleNamespace(done=True, succeeded=False),
        # 截图作业成功但缓冲区为空时 MaaFramework 返回 0x0 图像
        SimpleNamespace(
            done=True,
            succeeded=True,
            get=lambda: numpy.zeros((0, 0, 3), dtype=numpy.uint8),
        ),
    ],
)
def test_failed_notification_capture_keeps_device_connection(monkeypatch, job):
    monkeypatch.setattr("backend.maa_worker.worker.time.sleep", lambda _: None)
    controller = SimpleNamespace(post_screencap=lambda: job)
    logs: list[str] = []
    worker = SimpleNamespace(
        device_state=SimpleNamespace(connected=True, controller=controller),
        events=SimpleNamespace(send_log=logs.append),
    )

    assert MaaWorker.capture_notification_jpeg(cast(Any, worker)) is None

    # 任务可能正在用这台设备，附图失败不能解除连接
    assert worker.device_state.connected is True
    assert worker.device_state.controller is controller
    assert logs == ["通知截图失败，本次只发送文字"]


def test_stalled_notification_capture_times_out(monkeypatch):
    clock = iter([0.0, 5.0, 11.0])
    monkeypatch.setattr("backend.maa_worker.worker.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("backend.maa_worker.worker.time.sleep", lambda _: None)
    job = SimpleNamespace(done=False)
    logs: list[str] = []
    worker = SimpleNamespace(
        device_state=SimpleNamespace(
            connected=True, controller=SimpleNamespace(post_screencap=lambda: job)
        ),
        events=SimpleNamespace(send_log=logs.append),
    )

    assert MaaWorker.capture_notification_jpeg(cast(Any, worker)) is None
    assert logs == ["通知截图超时，本次只发送文字"]


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


def test_wecom_shrinks_screenshot_over_size_limit(monkeypatch):
    posts: list[dict[str, Any]] = []

    def post(_url, **kwargs):
        posts.append(kwargs["json"])
        return _Response({"errcode": 0})

    monkeypatch.setattr(notification_module.requests, "post", post)
    monkeypatch.setattr(notification_module, "_WECOM_IMAGE_LIMIT", 20_000)
    # 随机噪声几乎无法压缩，保证原图超过上限
    noise = Image.frombytes("RGB", (200, 200), random.Random(0).randbytes(120_000))
    buffer = io.BytesIO()
    noise.save(buffer, format="JPEG", quality=95)
    large = buffer.getvalue()
    assert len(large) > 20_000
    channel = WeComChannel(id="w", type="wecom", params={"key": "k"})

    assert send_external([channel], "任务失败", "Daily 执行失败", "error", large) == []

    image = base64.b64decode(posts[1]["image"]["base64"])
    assert len(image) <= 20_000
    assert posts[1]["image"]["md5"] == hashlib.md5(image).hexdigest()
    assert Image.open(io.BytesIO(image)).format == "JPEG"


@pytest.mark.parametrize(
    ("screenshot", "expected"), [(JPEG, base64.b64encode(JPEG).decode()), (None, "")]
)
def test_webhook_screenshot_placeholder(monkeypatch, screenshot, expected):
    sent = _capture_requests(monkeypatch)
    channel = _webhook(json.dumps({"text": "{{message}}", "image": "{{screenshot}}"}))

    assert send_external([channel], "t", "m", "info", screenshot) == []
    assert sent == [{"text": "m", "image": expected}]


@pytest.mark.parametrize(
    ("screenshot", "expected"),
    [
        (None, {"title": "t", "message": "m"}),
        (
            JPEG,
            {
                "title": "t",
                "message": "m",
                "screenshot": base64.b64encode(JPEG).decode(),
            },
        ),
    ],
)
def test_webhook_default_body_adds_screenshot_only_when_attached(
    monkeypatch, screenshot, expected
):
    sent = _capture_requests(monkeypatch)

    assert send_external([_webhook()], "t", "m", "info", screenshot) == []
    assert sent == [expected]
