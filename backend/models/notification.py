"""外部通知渠道配置：按 `type` 区分的渠道列表，参数均以字符串保存，发送时再转换。"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class _Channel(BaseModel):
    id: str
    enabled: bool = True


class DingTalkParams(BaseModel):
    # access_token 或完整 Webhook URL
    token: str = ""
    # 加签密钥（SEC 开头），可空
    secret: str = ""


class DingTalkChannel(_Channel):
    type: Literal["dingtalk"]
    params: DingTalkParams = DingTalkParams()


class FeishuParams(BaseModel):
    # hook token 或完整 Webhook URL（Lark 国际版填完整 URL）
    token: str = ""
    # 签名校验密钥，可空
    secret: str = ""


class FeishuChannel(_Channel):
    type: Literal["feishu"]
    params: FeishuParams = FeishuParams()


class WeComParams(BaseModel):
    # 机器人 key 或完整 Webhook URL
    key: str = ""


class WeComChannel(_Channel):
    type: Literal["wecom"]
    params: WeComParams = WeComParams()


class ServerChanParams(BaseModel):
    sendkey: str = ""


class ServerChanChannel(_Channel):
    type: Literal["serverchan"]
    params: ServerChanParams = ServerChanParams()


class OneBotParams(BaseModel):
    # OneBot 11 HTTP 服务地址，如 http://127.0.0.1:3000
    url: str = ""
    token: str = ""
    # 逗号分隔的 QQ 号 / 群号
    users: str = ""
    groups: str = ""


class OneBotChannel(_Channel):
    type: Literal["onebot"]
    params: OneBotParams = OneBotParams()


class SmtpParams(BaseModel):
    host: str = ""
    port: str = "465"
    security: Literal["ssl", "starttls", "none"] = "ssl"
    username: str = ""
    password: str = ""
    # 发件地址，空则用 username
    sender: str = ""
    # 逗号分隔的收件地址，空则发给发件地址
    to: str = ""


class SmtpChannel(_Channel):
    type: Literal["smtp"]
    params: SmtpParams = SmtpParams()


class TelegramParams(BaseModel):
    botToken: str = ""
    chatId: str = ""


class TelegramChannel(_Channel):
    type: Literal["telegram"]
    params: TelegramParams = TelegramParams()


class BarkParams(BaseModel):
    server: str = "https://api.day.app"
    deviceKey: str = ""


class BarkChannel(_Channel):
    type: Literal["bark"]
    params: BarkParams = BarkParams()


class WxPusherParams(BaseModel):
    appToken: str = ""
    # 逗号分隔的 UID（UID_ 开头）或主题 ID
    targets: str = ""


class WxPusherChannel(_Channel):
    type: Literal["wxpusher"]
    params: WxPusherParams = WxPusherParams()


class PushPlusParams(BaseModel):
    token: str = ""


class PushPlusChannel(_Channel):
    type: Literal["pushplus"]
    params: PushPlusParams = PushPlusParams()


class WebhookParams(BaseModel):
    url: str = ""
    method: Literal["POST", "GET"] = "POST"
    contentType: Literal["application/json", "application/x-www-form-urlencoded"] = (
        "application/json"
    )
    # JSON 对象字符串
    headers: str = ""
    # JSON 模板，支持 {{title}} / {{message}} 占位符；空则发送 {title, message}
    body: str = ""
    username: str = ""
    password: str = ""


class WebhookChannel(_Channel):
    type: Literal["webhook"]
    params: WebhookParams = WebhookParams()


type NotificationChannel = Annotated[
    DingTalkChannel
    | FeishuChannel
    | WeComChannel
    | ServerChanChannel
    | OneBotChannel
    | SmtpChannel
    | TelegramChannel
    | BarkChannel
    | WxPusherChannel
    | PushPlusChannel
    | WebhookChannel,
    Field(discriminator="type"),
]
