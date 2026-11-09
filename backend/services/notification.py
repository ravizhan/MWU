"""外部通知：把设置里的渠道转换成 apprise 插件实例并一次性发送。

apprise 按 URL schema 加载插件时会扫描插件目录，Nuitka standalone 产物里没有这些
源文件，所以这里直接实例化插件类，不走 URL。钉钉/飞书/企业微信群机器人出错时 HTTP
仍返回 200，apprise 自带插件只看状态码（飞书还不支持签名），因此由 _RobotWebhook 实现。

截图附件：邮件、Telegram、OneBot 由 apprise 插件原生发送；企业微信在文本后追加一条
图片消息；自定义 Webhook 通过 {{screenshot}} 占位符取 Base64；其余渠道只发文本。
"""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import requests
from apprise import Apprise, AppriseAsset, AppriseAttachment, NotifyFormat, NotifyType
from apprise.attachment.memory import AttachMemory
from apprise.exception import AppriseException
from apprise.plugins.bark import NotifyBark
from apprise.plugins.base import NotifyBase
from apprise.plugins.email import NotifyEmail
from apprise.plugins.onebot import NotifyOneBot
from apprise.plugins.pushplus import NotifyPushplus
from apprise.plugins.serverchan import NotifyServerChan
from apprise.plugins.telegram import NotifyTelegram
from apprise.plugins.wxpusher import NotifyWxPusher

from backend.models.api import RealtimeEventLevel
from backend.models.notification import (
    BarkChannel,
    DingTalkChannel,
    FeishuChannel,
    NotificationChannel,
    OneBotChannel,
    PushPlusChannel,
    ServerChanChannel,
    SmtpChannel,
    TelegramChannel,
    WebhookChannel,
    WeComChannel,
    WxPusherChannel,
)

_NOTIFY_TYPES: dict[RealtimeEventLevel, NotifyType] = {
    "info": NotifyType.INFO,
    "success": NotifyType.SUCCESS,
    "error": NotifyType.FAILURE,
}

# 插件会把 app_id 写进 User-Agent 等 HTTP/邮件头，只能用 ASCII；显示名走通知标题
_APP_ID = "MWU"

type _RobotRequest = tuple[str, dict[str, str], dict[str, Any]]


def _attachment_bytes(attach: AppriseAttachment | None) -> bytes | None:
    if not attach:
        return None
    with attach[0].open() as stream:
        return stream.read()


def _request_error(exc: requests.RequestException) -> str:
    """requests 的异常文本包含完整 URL（钉钉/企业微信的 token 在其中），只报状态码或异常类型。"""
    if exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


class _RobotWebhook(NotifyBase):
    """国内群机器人：POST JSON，并按响应体里的业务错误码判定成败。

    提供 build_image 的机器人在文本消息之后再发一条截图消息。
    """

    protocol = "mwu-robot"
    notify_format = NotifyFormat.TEXT
    # 标题并入正文（apprise 以换行拼接）
    title_maxlen = 0

    def __init__(
        self,
        service_name: str,
        build: Callable[[str], _RobotRequest],
        error_of: Callable[[dict[str, Any]], str | None],
        build_image: Callable[[bytes], _RobotRequest] | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.service_name = service_name
        self._build = build
        self._error_of = error_of
        self._build_image = build_image

    def url(self, privacy: bool = False, *args: Any, **kwargs: Any) -> str:
        return f"{self.protocol}://{self.service_name}"

    def send(
        self,
        body: str,
        title: str = "",
        notify_type: NotifyType = NotifyType.INFO,
        **kwargs: Any,
    ) -> bool:
        if not self._post(self._build(body)):
            return False
        image = _attachment_bytes(kwargs.get("attach"))
        if image is None or self._build_image is None:
            return True
        return self._post(self._build_image(image))

    def _post(self, request: _RobotRequest) -> bool:
        url, params, payload = request
        self.throttle()
        try:
            response = requests.post(
                url,
                params=params,
                json=payload,
                headers={"User-Agent": self.app_id},
                verify=self.verify_certificate,
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            error = self._error_of(response.json())
        except requests.RequestException as exc:
            self.logger.warning("请求失败: %s", _request_error(exc))
            return False
        except ValueError as exc:
            self.logger.warning("响应不是合法 JSON: %s", exc)
            return False
        if error is not None:
            self.logger.warning("返回错误: %s", error)
            return False
        return True


def _endpoint(value: str, default_prefix: str) -> str:
    value = value.strip()
    if not value:
        raise AppriseException("未填写 Webhook 地址")
    return (
        value if value.startswith(("http://", "https://")) else default_prefix + value
    )


def _errcode_error(data: dict[str, Any]) -> str | None:
    if data.get("errcode", 0) == 0:
        return None
    return f"{data.get('errcode')} {data.get('errmsg', '')}".strip()


def _feishu_error(data: dict[str, Any]) -> str | None:
    code = data.get("code", data.get("StatusCode", 0))
    if code == 0:
        return None
    return f"{code} {data.get('msg', data.get('StatusMessage', ''))}".strip()


def _dingtalk(channel: DingTalkChannel, **kwargs: Any) -> NotifyBase:
    p = channel.params
    url = _endpoint(p.token, "https://oapi.dingtalk.com/robot/send?access_token=")

    def build(body: str) -> _RobotRequest:
        params: dict[str, str] = {}
        if p.secret:
            timestamp = str(round(time.time() * 1000))
            digest = hmac.new(
                p.secret.encode(),
                f"{timestamp}\n{p.secret}".encode(),
                hashlib.sha256,
            ).digest()
            params = {
                "timestamp": timestamp,
                "sign": base64.b64encode(digest).decode(),
            }
        return url, params, {"msgtype": "text", "text": {"content": body}}

    return _RobotWebhook("钉钉", build, _errcode_error, **kwargs)


def _feishu(channel: FeishuChannel, **kwargs: Any) -> NotifyBase:
    p = channel.params
    url = _endpoint(p.token, "https://open.feishu.cn/open-apis/bot/v2/hook/")

    def build(body: str) -> _RobotRequest:
        payload: dict[str, Any] = {"msg_type": "text", "content": {"text": body}}
        if p.secret:
            # 飞书签名：以「timestamp\nsecret」为密钥对空串做 HMAC-SHA256
            timestamp = str(int(time.time()))
            key = f"{timestamp}\n{p.secret}".encode()
            digest = hmac.new(key, b"", hashlib.sha256).digest()
            payload |= {
                "timestamp": timestamp,
                "sign": base64.b64encode(digest).decode(),
            }
        return url, {}, payload

    return _RobotWebhook("飞书", build, _feishu_error, **kwargs)


def _wecom(channel: WeComChannel, **kwargs: Any) -> NotifyBase:
    url = _endpoint(
        channel.params.key, "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key="
    )

    def build(body: str) -> _RobotRequest:
        return url, {}, {"msgtype": "text", "text": {"content": body}}

    def build_image(image: bytes) -> _RobotRequest:
        payload = {
            "msgtype": "image",
            "image": {
                "base64": base64.b64encode(image).decode(),
                "md5": hashlib.md5(image).hexdigest(),
            },
        }
        return url, {}, payload

    return _RobotWebhook("企业微信", build, _errcode_error, build_image, **kwargs)


class _Webhook(NotifyBase):
    """自定义 Webhook：JSON 模板支持 {{title}} / {{message}} / {{screenshot}}（Base64 JPEG，
    无截图时为空串），可选 GET、表单与 Basic 认证。"""

    service_name = "Webhook"
    protocol = "mwu-webhook"
    notify_format = NotifyFormat.TEXT

    def __init__(self, channel: WebhookChannel, **kwargs: Any):
        super().__init__(**kwargs)
        if not channel.params.url.strip():
            raise AppriseException("未填写 URL")
        self._params = channel.params
        try:
            self._headers = (
                json.loads(channel.params.headers) if channel.params.headers else {}
            )
        except ValueError as exc:
            raise AppriseException(f"Headers 不是合法 JSON: {exc}") from exc

    def url(self, privacy: bool = False, *args: Any, **kwargs: Any) -> str:
        return f"{self.protocol}://"

    def send(
        self,
        body: str,
        title: str = "",
        notify_type: NotifyType = NotifyType.INFO,
        **kwargs: Any,
    ) -> bool:
        p = self._params
        template = p.body.strip()
        image = _attachment_bytes(kwargs.get("attach"))
        screenshot = base64.b64encode(image).decode() if image else ""

        def escape(value: str) -> str:
            # 编码成 JSON 字符串字面量再去掉两侧引号，占位符在字符串内时结果仍是合法 JSON
            return json.dumps(value, ensure_ascii=False)[1:-1]

        try:
            payload = (
                json.loads(
                    template.replace("{{title}}", escape(title))
                    .replace("{{message}}", escape(body))
                    .replace("{{screenshot}}", screenshot)
                )
                if template
                else {"title": title, "message": body, "screenshot": screenshot}
            )
        except ValueError as exc:
            self.logger.warning("Body 模板不是合法 JSON: %s", exc)
            return False

        request: dict[str, Any] = {
            "headers": self._headers,
            "timeout": self.request_timeout,
            "verify": self.verify_certificate,
        }
        if p.username and p.password:
            request["auth"] = (p.username, p.password)
        if p.method == "GET":
            request["params"] = payload
        elif p.contentType == "application/json":
            request["json"] = payload
        else:
            request["data"] = payload

        self.throttle()
        try:
            requests.request(p.method, p.url, **request).raise_for_status()
        except requests.RequestException as exc:
            self.logger.warning("请求失败: %s", _request_error(exc))
            return False
        return True


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _server(url: str) -> dict[str, Any]:
    """把 http(s)://host[:port] 拆成 apprise URLBase 的 host/port/secure 参数。"""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise AppriseException(f"服务地址无效: {url}")
    return {
        "host": parts.hostname,
        "port": parts.port,
        "secure": parts.scheme == "https",
    }


def _onebot(channel: OneBotChannel, **kwargs: Any) -> NotifyBase:
    p = channel.params
    targets = _split(p.users) + [f"#{group}" for group in _split(p.groups)]
    return NotifyOneBot(
        token=p.token or None, targets=targets, **_server(p.url), **kwargs
    )


def _smtp(channel: SmtpChannel, **kwargs: Any) -> NotifyBase:
    p = channel.params
    sender = p.sender or p.username
    return NotifyEmail(
        host=p.host,
        port=int(p.port),
        user=p.username,
        password=p.password,
        secure=p.security != "none",
        secure_mode="insecure" if p.security == "none" else p.security,
        from_addr=sender,
        targets=_split(p.to) or [sender],
        **kwargs,
    )


def _bark(channel: BarkChannel, **kwargs: Any) -> NotifyBase:
    p = channel.params
    return NotifyBark(targets=[p.deviceKey], **_server(p.server), **kwargs)


def _build_plugin(channel: NotificationChannel, asset: AppriseAsset) -> NotifyBase:
    kwargs: dict[str, Any] = {"asset": asset}
    match channel:
        case DingTalkChannel():
            return _dingtalk(channel, **kwargs)
        case FeishuChannel():
            return _feishu(channel, **kwargs)
        case WeComChannel():
            return _wecom(channel, **kwargs)
        case ServerChanChannel():
            return NotifyServerChan(token=channel.params.sendkey, **kwargs)
        case OneBotChannel():
            return _onebot(channel, **kwargs)
        case SmtpChannel():
            return _smtp(channel, **kwargs)
        case TelegramChannel():
            return NotifyTelegram(
                bot_token=channel.params.botToken,
                targets=_split(channel.params.chatId),
                **kwargs,
            )
        case BarkChannel():
            return _bark(channel, **kwargs)
        case WxPusherChannel():
            return NotifyWxPusher(
                token=channel.params.appToken,
                targets=_split(channel.params.targets),
                **kwargs,
            )
        case PushPlusChannel():
            return NotifyPushplus(token=channel.params.token, **kwargs)
        case WebhookChannel():
            return _Webhook(channel, **kwargs)


def send_external(
    channels: list[NotificationChannel],
    title: str,
    message: str,
    level: RealtimeEventLevel,
    screenshot: bytes | None = None,
) -> list[str]:
    """向所有启用的渠道发送通知，返回每个失败渠道的错误描述（全部成功时为空）。

    screenshot 为 JPEG 字节，支持附件的渠道随通知一起发送。
    """
    asset = AppriseAsset(app_id=_APP_ID, storage_mode="memory")
    apprise = Apprise(asset=asset)
    errors: list[str] = []
    for channel in channels:
        if not channel.enabled:
            continue
        try:
            apprise.add(_build_plugin(channel, asset))
        except (AppriseException, ValueError, TypeError) as exc:
            errors.append(f"{channel.type} 配置无效: {exc}")

    if not len(apprise):
        return errors

    attach = (
        AppriseAttachment(
            AttachMemory(
                content=screenshot, name="screenshot.jpg", mimetype="image/jpeg"
            ),
            asset=asset,
        )
        if screenshot
        else None
    )
    result = apprise.notify(
        body=message,
        title=title,
        notify_type=_NOTIFY_TYPES[level],
        body_format=NotifyFormat.TEXT,
        attach=attach,
    )
    for service in result:
        if service:
            continue
        details = "; ".join(entry.message for entry in service.logs()) or "未知错误"
        errors.append(f"{service.name}: {details}")
    return errors
