import type { NotificationChannelType } from "@/types/settingsModel"

type Translate = (key: string) => string

export interface ChannelField {
  key: string
  label: string
  kind: "text" | "password" | "textarea" | "select"
  default: string
  placeholder?: string
  options?: { label: string; value: string }[]
  wide?: boolean
  /** 返回 false 时隐藏该字段（如 GET 请求不需要 Content-Type） */
  visible?: (params: Record<string, string>) => boolean
}

export interface ChannelDefinition {
  type: NotificationChannelType
  label: string
  fields: ChannelField[]
}

export const CHANNEL_TYPES: readonly NotificationChannelType[] = [
  "dingtalk",
  "feishu",
  "wecom",
  "serverchan",
  "onebot",
  "smtp",
  "wxpusher",
  "pushplus",
  "bark",
  "telegram",
  "webhook",
]

export function findChannelType(value: unknown): NotificationChannelType | undefined {
  return CHANNEL_TYPES.find((type) => type === value)
}

/** 渠道字段定义，键名与默认值须与后端 backend/models/notification.py 一致 */
export function channelDefinitions(
  t: Translate,
): Record<NotificationChannelType, ChannelDefinition> {
  const field = (
    key: string,
    label: string,
    kind: ChannelField["kind"] = "text",
    extra: Partial<ChannelField> = {},
  ): ChannelField => ({ key, label, kind, default: "", ...extra })

  return {
    dingtalk: {
      type: "dingtalk",
      label: t("settings.notification.channelTypes.dingtalk"),
      fields: [
        field("token", t("settings.notification.fields.webhookToken"), "password", {
          placeholder: "https://oapi.dingtalk.com/robot/send?access_token=...",
          wide: true,
        }),
        field("secret", t("settings.notification.fields.secret"), "password", {
          placeholder: "SEC...",
          wide: true,
        }),
      ],
    },
    feishu: {
      type: "feishu",
      label: t("settings.notification.channelTypes.feishu"),
      fields: [
        field("token", t("settings.notification.fields.webhookToken"), "password", {
          placeholder: "https://open.feishu.cn/open-apis/bot/v2/hook/...",
          wide: true,
        }),
        field("secret", t("settings.notification.fields.secret"), "password", { wide: true }),
      ],
    },
    wecom: {
      type: "wecom",
      label: t("settings.notification.channelTypes.wecom"),
      fields: [
        field("key", t("settings.notification.fields.webhookKey"), "password", {
          placeholder: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...",
          wide: true,
        }),
      ],
    },
    serverchan: {
      type: "serverchan",
      label: t("settings.notification.channelTypes.serverchan"),
      fields: [
        field("sendkey", t("settings.notification.fields.sendkey"), "password", {
          placeholder: "SCT...",
          wide: true,
        }),
      ],
    },
    onebot: {
      type: "onebot",
      label: t("settings.notification.channelTypes.onebot"),
      fields: [
        field("url", t("settings.notification.fields.serviceUrl"), "text", {
          placeholder: "http://127.0.0.1:3000",
        }),
        field("token", t("settings.notification.fields.accessToken"), "password"),
        field("users", t("settings.notification.fields.qqUsers"), "text", {
          placeholder: "123456, 234567",
        }),
        field("groups", t("settings.notification.fields.qqGroups"), "text", {
          placeholder: "123456, 234567",
        }),
      ],
    },
    smtp: {
      type: "smtp",
      label: t("settings.notification.channelTypes.smtp"),
      fields: [
        field("host", t("settings.notification.fields.smtpHost"), "text", {
          placeholder: "smtp.qq.com",
        }),
        field("port", t("settings.notification.fields.port"), "text", { default: "465" }),
        field("security", t("settings.notification.fields.security"), "select", {
          default: "ssl",
          options: [
            { label: "SSL/TLS", value: "ssl" },
            { label: "STARTTLS", value: "starttls" },
            { label: t("settings.notification.fields.noEncryption"), value: "none" },
          ],
        }),
        field("username", t("settings.notification.fields.username")),
        field("password", t("settings.notification.fields.smtpPassword"), "password"),
        field("sender", t("settings.notification.fields.sender"), "text", {
          placeholder: t("settings.notification.fields.senderPlaceholder"),
        }),
        field("to", t("settings.notification.fields.recipients"), "text", {
          placeholder: t("settings.notification.fields.recipientsPlaceholder"),
          wide: true,
        }),
      ],
    },
    wxpusher: {
      type: "wxpusher",
      label: t("settings.notification.channelTypes.wxpusher"),
      fields: [
        field("appToken", t("settings.notification.fields.appToken"), "password", {
          placeholder: "AT_...",
        }),
        field("targets", t("settings.notification.fields.wxpusherTargets"), "text", {
          placeholder: "UID_..., UID_...",
        }),
      ],
    },
    pushplus: {
      type: "pushplus",
      label: t("settings.notification.channelTypes.pushplus"),
      fields: [field("token", t("settings.notification.fields.token"), "password", { wide: true })],
    },
    bark: {
      type: "bark",
      label: t("settings.notification.channelTypes.bark"),
      fields: [
        field("server", t("settings.notification.fields.serviceUrl"), "text", {
          default: "https://api.day.app",
        }),
        field("deviceKey", t("settings.notification.fields.deviceKey"), "password"),
      ],
    },
    telegram: {
      type: "telegram",
      label: t("settings.notification.channelTypes.telegram"),
      fields: [
        field("botToken", t("settings.notification.fields.botToken"), "password"),
        field("chatId", t("settings.notification.fields.chatId")),
      ],
    },
    webhook: {
      type: "webhook",
      label: t("settings.notification.channelTypes.webhook"),
      fields: [
        field("url", t("settings.notification.fields.url"), "text", {
          placeholder: "https://...",
          wide: true,
        }),
        field("method", t("settings.notification.fields.method"), "select", {
          default: "POST",
          options: [
            { label: t("settings.notification.fields.post"), value: "POST" },
            { label: t("settings.notification.fields.get"), value: "GET" },
          ],
        }),
        field("contentType", t("settings.notification.fields.contentType"), "select", {
          default: "application/json",
          options: [
            { label: t("settings.notification.fields.json"), value: "application/json" },
            {
              label: t("settings.notification.fields.formUrlencoded"),
              value: "application/x-www-form-urlencoded",
            },
          ],
          visible: (params) => params.method !== "GET",
        }),
        field("headers", t("settings.notification.fields.headers"), "text", {
          placeholder: '{"Authorization":"Bearer ..."}',
          wide: true,
        }),
        field("body", t("settings.notification.fields.body"), "textarea", {
          placeholder: '{"desp":"{{message}}","title":"{{title}}"}',
          wide: true,
        }),
        field("username", t("settings.notification.fields.username")),
        field("password", t("settings.notification.fields.password"), "password"),
      ],
    },
  }
}
