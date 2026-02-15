<template>
  <n-message-provider>
    <div class="flex p-5 gap-6 h-[80vh] overflow-y-auto max-md:flex-col max-md:p-3">
      <div
        class="sticky top-5 w-45 shrink-0 h-fit max-md:relative max-md:top-0 max-md:w-full max-md:mb-4"
      >
        <n-anchor
          :show-rail="true"
          :show-background="true"
          :bound="80"
          type="block"
          offset-target="#setting-content"
        >
          <n-anchor-link :title="t('settings.anchor.update')" href="#update-settings">
            <template #icon>
              <n-icon><div class="i-mdi-update" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link :title="t('settings.anchor.runtime')" href="#runtime-settings">
            <template #icon>
              <n-icon><div class="i-mdi-cog-play" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link :title="t('settings.anchor.scheduler')" href="#scheduler-settings">
            <template #icon>
              <n-icon><div class="i-mdi-clock-outline" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link :title="t('settings.anchor.ui')" href="#ui-settings">
            <template #icon>
              <n-icon><div class="i-mdi-palette" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link :title="t('settings.anchor.notification')" href="#notification-settings">
            <template #icon>
              <n-icon><div class="i-mdi-bell" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link :title="t('settings.anchor.about')" href="#about">
            <template #icon>
              <n-icon><div class="i-mdi-information" /></n-icon>
            </template>
          </n-anchor-link>
        </n-anchor>
      </div>
      <div id="setting-content" class="flex-1 overflow-y-auto max-md:max-w-full">
        <n-scrollbar>
          <!-- 更新设置 -->
          <n-card
            id="update-settings"
            class="mb-6 scroll-mt-5 last:mb-0"
            :title="t('settings.update.title')"
          >
            <template #header-extra>
              <n-button
                size="small"
                type="primary"
                @click="checkForUpdate"
                :loading="checkingUpdate"
              >
                {{ t("settings.update.check") }}
              </n-button>
            </template>
            <n-form label-placement="left" label-width="120">
              <n-form-item :label="t('settings.update.auto')">
                <n-switch
                  v-model:value="settings.update.autoUpdate"
                  @update:value="(val: boolean) => handleSettingChange('update', 'autoUpdate', val)"
                />
              </n-form-item>
              <n-form-item :label="t('settings.update.channel')">
                <n-select
                  v-model:value="settings.update.updateChannel"
                  :options="updateChannelOptions"
                  @update:value="
                    (val: string) =>
                      handleSettingChange(
                        'update',
                        'updateChannel',
                        val as SettingsModel['update']['updateChannel'],
                      )
                  "
                />
              </n-form-item>
              <n-form-item :label="t('settings.update.proxy')">
                <n-input
                  v-model:value="settings.update.proxy"
                  placeholder="http://127.0.0.1:7890"
                  clearable
                  @blur="handleSettingChange('update', 'proxy', settings.update.proxy)"
                />
              </n-form-item>
              <n-form-item
                v-if="interfaceStore.interface?.mirrorchyan_rid"
                :label="t('settings.update.mirrorchyanCdk')"
              >
                <n-input-group>
                  <n-input
                    v-model:value="settings.update.mirrorchyanCdk"
                    type="password"
                    show-password-on="click"
                    :placeholder="t('settings.update.mirrorchyanCdkPlaceholder')"
                    clearable
                    @blur="
                      handleSettingChange(
                        'update',
                        'mirrorchyanCdk',
                        settings.update.mirrorchyanCdk,
                      )
                    "
                  />
                  <n-button
                    tag="a"
                    href="https://mirrorchyan.com"
                    target="_blank"
                    type="primary"
                    ghost
                  >
                    {{ t("settings.update.mirrorchyanCdkHint") }}
                  </n-button>
                </n-input-group>
              </n-form-item>
            </n-form>
          </n-card>

          <!-- 运行设置 -->
          <n-card
            id="runtime-settings"
            class="mb-6 scroll-mt-5 last:mb-0"
            :title="t('settings.runtime.title')"
          >
            <n-form label-placement="left" label-width="120">
              <n-form-item :label="t('settings.runtime.timeout')">
                <n-input-number
                  v-model:value="settings.runtime.timeout"
                  :min="60"
                  :max="3600"
                  :step="30"
                  @update:value="
                    (val: number | null) => handleSettingChange('runtime', 'timeout', val)
                  "
                >
                  <template #suffix>{{ t("settings.runtime.timeoutSuffix") }}</template>
                </n-input-number>
              </n-form-item>
              <n-form-item :label="t('settings.runtime.reminderInterval')">
                <n-input-number
                  v-model:value="settings.runtime.reminderInterval"
                  :min="5"
                  :max="120"
                  :step="5"
                  @update:value="
                    (val: number | null) => handleSettingChange('runtime', 'reminderInterval', val)
                  "
                >
                  <template #suffix>{{ t("settings.runtime.reminderSuffix") }}</template>
                </n-input-number>
              </n-form-item>
              <n-form-item :label="t('settings.runtime.autoRetry')">
                <n-switch
                  v-model:value="settings.runtime.autoRetry"
                  @update:value="(val: boolean) => handleSettingChange('runtime', 'autoRetry', val)"
                />
              </n-form-item>
              <n-form-item
                :label="t('settings.runtime.maxRetryCount')"
                v-if="settings.runtime.autoRetry"
              >
                <n-input-number
                  v-model:value="settings.runtime.maxRetryCount"
                  :min="1"
                  :max="10"
                  @update:value="
                    (val: number | null) => handleSettingChange('runtime', 'maxRetryCount', val)
                  "
                />
              </n-form-item>
            </n-form>
          </n-card>

          <!-- 定时任务设置 -->
          <n-card
            id="scheduler-settings"
            class="mb-6 scroll-mt-5 last:mb-0"
            :title="t('settings.scheduler.title')"
          >
            <template #header-extra>
              <n-button size="small" type="primary" @click="openCreateTaskDialog">
                <template #icon>
                  <n-icon><div class="i-mdi-plus" /></n-icon>
                </template>
                {{ t("settings.scheduler.create") }}
              </n-button>
            </template>

            <n-collapse>
              <!-- 任务列表折叠面板 -->
              <n-collapse-item :title="t('settings.scheduler.taskList')" name="tasks">
                <n-empty
                  v-if="schedulerStore.tasks.length === 0"
                  :description="t('settings.scheduler.noTasks')"
                />
                <n-list v-else>
                  <n-list-item v-for="task in schedulerStore.tasks" :key="task.id">
                    <template #prefix>
                      <n-switch
                        :value="task.enabled"
                        @update:value="(val: boolean) => handleToggleTask(task.id, val)"
                      />
                    </template>
                    <n-thing :title="task.name" :description="task.description">
                      <template #header-extra>
                        <n-space>
                          <n-button size="tiny" @click="openEditTaskDialog(task)">{{
                            t("common.edit")
                          }}</n-button>
                          <n-button size="tiny" type="error" @click="handleDeleteTask(task.id)">{{
                            t("common.delete")
                          }}</n-button>
                        </n-space>
                      </template>
                      <template #description>
                        <n-space vertical size="small">
                          <n-text depth="3"
                            >{{ t("settings.scheduler.trigger") }}:
                            {{ formatTrigger(task.trigger_type, task.trigger_config) }}</n-text
                          >
                          <n-text depth="3"
                            >{{ t("settings.scheduler.nextRun") }}:
                            {{ formatDateTime(task.next_run_time) }}</n-text
                          >
                        </n-space>
                      </template>
                    </n-thing>
                  </n-list-item>
                </n-list>
              </n-collapse-item>

              <!-- 执行历史折叠面板 -->
              <n-collapse-item :title="t('settings.scheduler.history')" name="history">
                <n-empty
                  v-if="schedulerStore.executions.length === 0"
                  :description="t('settings.scheduler.noHistory')"
                />
                <n-timeline v-else>
                  <n-timeline-item
                    v-for="exec in schedulerStore.executions"
                    :key="exec.id"
                    :type="getStatusType(exec.status)"
                    :title="exec.task_name"
                    :time="formatDateTime(exec.started_at)"
                  >
                    <template #icon>
                      <n-icon>
                        <div :class="getStatusIcon(exec.status)" />
                      </n-icon>
                    </template>
                    <n-text :type="getStatusTextType(exec.status)">
                      {{ getStatusLabel(exec.status) }}
                    </n-text>
                    <n-text v-if="exec.error_message" type="error" depth="3">
                      {{ exec.error_message }}
                    </n-text>
                  </n-timeline-item>
                </n-timeline>
              </n-collapse-item>
            </n-collapse>
          </n-card>

          <!-- 界面设置 -->
          <n-card
            id="ui-settings"
            class="mb-6 scroll-mt-5 last:mb-0"
            :title="t('settings.ui.title')"
          >
            <n-form label-placement="left" label-width="120">
              <n-form-item :label="t('settings.ui.language')">
                <n-select
                  :value="locale"
                  :options="localeOptions"
                  @update:value="handleLocaleChange"
                />
              </n-form-item>
              <n-form-item :label="t('settings.ui.darkMode')">
                <n-select
                  v-model:value="settings.ui.darkMode"
                  :options="darkModeOptions"
                  @update:value="
                    (val: string | boolean) =>
                      (val === 'auto' || typeof val === 'boolean') &&
                      handleSettingChange('ui', 'darkMode', val as SettingsModel['ui']['darkMode'])
                  "
                />
              </n-form-item>
            </n-form>
          </n-card>

          <!-- 通知设置 -->
          <n-card
            id="notification-settings"
            class="mb-6 scroll-mt-5 last:mb-0"
            :title="t('settings.notification.title')"
          >
            <template #header-extra>
              <n-button
                size="small"
                type="info"
                @click="testNotification"
                :disabled="
                  !settings.notification.externalNotification || !settings.notification.webhook
                "
              >
                {{ t("settings.notification.test") }}
              </n-button>
            </template>
            <n-form label-placement="left" label-width="120">
              <n-form-item :label="t('settings.notification.enable')">
                <n-space>
                  <n-checkbox
                    v-model:checked="settings.notification.systemNotification"
                    @update:checked="
                      (val: boolean) =>
                        handleSettingChange('notification', 'systemNotification', val)
                    "
                  >
                    {{ t("settings.notification.system") }}
                  </n-checkbox>
                  <n-checkbox
                    v-model:checked="settings.notification.browserNotification"
                    @update:checked="
                      (val: boolean) =>
                        handleSettingChange('notification', 'browserNotification', val)
                    "
                  >
                    {{ t("settings.notification.browser") }}
                  </n-checkbox>
                  <n-checkbox
                    v-model:checked="settings.notification.externalNotification"
                    @update:checked="
                      (val: boolean) =>
                        handleSettingChange('notification', 'externalNotification', val)
                    "
                  >
                    {{ t("settings.notification.external") }}
                  </n-checkbox>
                </n-space>
              </n-form-item>
            </n-form>
            <template v-if="settings.notification.externalNotification">
              <n-form label-placement="top">
                <n-form-item label="url *">
                  <n-input
                    v-model:value="settings.notification.webhook"
                    placeholder="https://..."
                    @blur="
                      handleSettingChange('notification', 'webhook', settings.notification.webhook)
                    "
                  />
                </n-form-item>
                <n-form-item label="content_type" v-if="settings.notification.method !== 'GET'">
                  <n-select
                    v-model:value="settings.notification.contentType"
                    :options="contentTypeOptions"
                    @update:value="
                      (val: string) =>
                        handleSettingChange(
                          'notification',
                          'contentType',
                          val as SettingsModel['notification']['contentType'],
                        )
                    "
                  />
                </n-form-item>
                <n-form-item label="headers">
                  <n-input
                    v-model:value="settings.notification.headers"
                    placeholder="HTTP headers in JSON format"
                    @blur="
                      handleSettingChange('notification', 'headers', settings.notification.headers)
                    "
                  />
                </n-form-item>
                <n-form-item label="body">
                  <n-input
                    v-model:value="settings.notification.body"
                    type="textarea"
                    placeholder='{"desp":"{{message}}","title":"{{title}}"}'
                    :autosize="{ minRows: 2, maxRows: 5 }"
                    @blur="handleSettingChange('notification', 'body', settings.notification.body)"
                  />
                </n-form-item>
                <n-form-item label="username">
                  <n-input
                    v-model:value="settings.notification.username"
                    @blur="
                      handleSettingChange(
                        'notification',
                        'username',
                        settings.notification.username,
                      )
                    "
                  />
                </n-form-item>
                <n-form-item label="password">
                  <n-input
                    v-model:value="settings.notification.password"
                    type="password"
                    show-password-on="click"
                    @blur="
                      handleSettingChange(
                        'notification',
                        'password',
                        settings.notification.password,
                      )
                    "
                  />
                </n-form-item>
                <n-form-item label="method">
                  <n-select
                    v-model:value="settings.notification.method"
                    :options="methodOptions"
                    @update:value="
                      (val: string) =>
                        handleSettingChange(
                          'notification',
                          'method',
                          val as SettingsModel['notification']['method'],
                        )
                    "
                  />
                </n-form-item>
              </n-form>
            </template>
            <n-divider />
            <n-form label-placement="left" label-width="120">
              <n-form-item :label="t('settings.notification.onComplete')">
                <n-switch
                  v-model:value="settings.notification.notifyOnComplete"
                  @update:value="
                    (val: boolean) => handleSettingChange('notification', 'notifyOnComplete', val)
                  "
                />
              </n-form-item>
              <n-form-item :label="t('settings.notification.onError')">
                <n-switch
                  v-model:value="settings.notification.notifyOnError"
                  @update:value="
                    (val: boolean) => handleSettingChange('notification', 'notifyOnError', val)
                  "
                />
              </n-form-item>
            </n-form>
          </n-card>

          <!-- 关于我们 -->
          <n-card id="about" class="mb-6 scroll-mt-5 last:mb-0" :title="t('settings.about.title')">
            <n-descriptions bordered :column="1">
              <n-descriptions-item :label="t('settings.about.version')">
                {{ settings.about.version || t("common.unknown") }}
              </n-descriptions-item>
              <n-descriptions-item :label="t('settings.about.author')">
                {{ settings.about.author || t("common.unknown") }}
              </n-descriptions-item>
              <n-descriptions-item :label="t('settings.about.license')">
                {{ settings.about.license || "MIT" }}
              </n-descriptions-item>
              <n-descriptions-item :label="t('settings.about.homepage')">
                <n-button
                  text
                  tag="a"
                  :href="settings.about.github || 'https://github.com/ravizhan/MWU'"
                  target="_blank"
                  type="primary"
                >
                  <template #icon>
                    <n-icon><div class="i-mdi-github" /></n-icon>
                  </template>
                  {{ settings.about.github || "https://github.com/ravizhan/MWU" }}
                </n-button>
              </n-descriptions-item>
              <n-descriptions-item :label="t('settings.about.issue')">
                <n-button
                  text
                  tag="a"
                  :href="settings.about.issueUrl || 'https://github.com/ravizhan/MWU/issues'"
                  target="_blank"
                  type="primary"
                >
                  <template #icon>
                    <n-icon><div class="i-mdi-bug" /></n-icon>
                  </template>
                  GitHub Issues
                </n-button>
              </n-descriptions-item>
              <n-descriptions-item
                :label="t('settings.about.contact')"
                v-if="settings.about.contact"
              >
                {{ settings.about.contact }}
              </n-descriptions-item>
              <n-descriptions-item :label="t('settings.about.description')">
                {{ settings.about.description || t("settings.about.defaultDescription") }}
              </n-descriptions-item>
            </n-descriptions>
            <n-divider />
            <n-space>
              <n-button type="warning" @click="handleResetSettings">
                {{ t("settings.about.reset") }}
              </n-button>
            </n-space>
          </n-card>
        </n-scrollbar>
      </div>
    </div>

    <!-- 定时任务弹窗 -->
    <SchedulerTaskDialog
      v-model:show="showTaskDialog"
      :task="editingTask"
      @saved="handleTaskSaved"
    />

    <!-- 更新弹窗 -->
    <UpdateDialog v-model:show="showUpdateDialog" :update-info="updateInfo" />
  </n-message-provider>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from "vue"
import { useSettingsStore } from "../stores/settings"
import { useInterfaceStore } from "../stores/interface"
import { useSchedulerStore } from "../stores/scheduler"
import { checkUpdateApi, testNotificationApi, type UpdateInfo } from "../script/api"
import { useMessage, useDialog } from "naive-ui"
import { useI18n } from "vue-i18n"
import type { SettingsModel } from "../types/settings"
import type { ScheduledTask, TriggerConfig, ExecutionStatus } from "../types/scheduler"
import SchedulerTaskDialog from "../components/SchedulerTaskDialog.vue"
import UpdateDialog from "../components/UpdateDialog.vue"

type EditableCategory = Exclude<keyof SettingsModel, "about">
type MaybeNullForNumbers<T> = T extends number ? T | null : T
type EditableSettingValue<
  K extends EditableCategory,
  P extends keyof SettingsModel[K],
> = MaybeNullForNumbers<SettingsModel[K][P]>

const message = useMessage()
const dialog = useDialog()
const { t, locale } = useI18n()
const settingsStore = useSettingsStore()
const interfaceStore = useInterfaceStore()

const localeOptions = [
  { label: "简体中文", value: "zh-CN" },
  { label: "English", value: "en-US" },
]

const handleLocaleChange = (val: string) => {
  locale.value = val
  localStorage.setItem("locale", val)
}

const schedulerStore = useSchedulerStore()

if (typeof window !== "undefined") {
  window.$message = message
}

const settings = computed<SettingsModel>(() => settingsStore.settings)

const checkingUpdate = ref(false)
const showTaskDialog = ref(false)
const editingTask = ref<ScheduledTask | null>(null)
const showUpdateDialog = ref(false)
const updateInfo = ref<UpdateInfo | null>(null)

const updateChannelOptions = computed(() => [
  { label: t("settings.update.channelOptions.stable"), value: "stable" },
  { label: t("settings.update.channelOptions.beta"), value: "beta" },
])

const methodOptions = [
  { label: "POST", value: "POST" },
  { label: "GET", value: "GET" },
]

const contentTypeOptions = [
  { label: "application/json", value: "application/json" },
  { label: "application/x-www-form-urlencoded", value: "application/x-www-form-urlencoded" },
]

const darkModeOptions = computed(() => [
  { label: t("settings.ui.darkModeOptions.auto"), value: "auto" },
  { label: t("settings.ui.darkModeOptions.off"), value: false },
  { label: t("settings.ui.darkModeOptions.on"), value: true },
])

onMounted(() => {
  if (!settingsStore.initialized) {
    settingsStore.fetchSettings()
  }
  // 加载定时任务数据
  schedulerStore.fetchTasks()
  schedulerStore.fetchExecutions()
})

const handleSettingChange = async <K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: EditableSettingValue<K, P>,
) => {
  if (value === null) return
  await settingsStore.updateSetting(category, key, value as SettingsModel[K][P])
}

const checkForUpdate = async () => {
  checkingUpdate.value = true
  try {
    const result = await checkUpdateApi()
    if (result.status === "success" && result.update_info?.is_update_available) {
      updateInfo.value = result.update_info
      showUpdateDialog.value = true
    } else {
      message.success(t("settings.update.latest"))
    }
  } catch (error) {
    message.error(t("settings.update.failed"))
  } finally {
    checkingUpdate.value = false
  }
}

const testNotification = async () => {
  message.info(t("settings.notification.testSending"))
  try {
    const result = await testNotificationApi()
    if (result.status === "success") {
      message.success(t("settings.notification.testSuccess"))
    } else {
      message.error(t("settings.notification.testResult", { message: result.message }))
    }
  } catch (error) {
    message.error(t("settings.notification.testError"))
    console.error(error)
  }
}

const handleResetSettings = () => {
  dialog.warning({
    title: t("common.confirm"),
    content: t("settings.about.resetConfirm"),
    positiveText: t("common.confirm"),
    negativeText: t("common.cancel"),
    onPositiveClick: async () => {
      const success = await settingsStore.resetSettings()
      if (success) {
        message.success(t("settings.about.resetSuccess"))
      }
    },
  })
}

// ==================== 定时任务相关 ====================

function openCreateTaskDialog() {
  editingTask.value = null
  showTaskDialog.value = true
}

function openEditTaskDialog(task: ScheduledTask) {
  editingTask.value = task
  showTaskDialog.value = true
}

async function handleToggleTask(taskId: string, enabled: boolean) {
  await schedulerStore.toggleTask(taskId, enabled)
  if (schedulerStore.error) {
    message.error(schedulerStore.error)
  }
}

async function handleDeleteTask(taskId: string) {
  dialog.warning({
    title: t("common.delete"),
    content: t("settings.scheduler.deleteConfirm"),
    positiveText: t("common.confirm"),
    negativeText: t("common.cancel"),
    onPositiveClick: async () => {
      const success = await schedulerStore.deleteTask(taskId)
      if (success) {
        message.success(t("settings.scheduler.deleted"))
      } else {
        message.error(schedulerStore.error || t("common.fail"))
      }
    },
  })
}

function handleTaskSaved() {
  schedulerStore.fetchTasks()
  schedulerStore.fetchExecutions()
}

function formatTrigger(triggerType: string, triggerConfig: TriggerConfig): string {
  switch (triggerType) {
    case "cron":
      return `${t("settings.scheduler.formatter.cron")} ${(triggerConfig as any).cron}`
    case "date":
      return `${t("settings.scheduler.formatter.date")} ${formatDateTime((triggerConfig as any).run_date)}`
    case "interval":
      const config = triggerConfig as any
      const parts: string[] = []
      if (config.hours) parts.push(`${config.hours}${t("settings.scheduler.formatter.hour")}`)
      if (config.minutes) parts.push(`${config.minutes}${t("settings.scheduler.formatter.minute")}`)
      return `${t("settings.scheduler.formatter.interval")} ${parts.join(" ")}`
    default:
      return t("common.unknown")
  }
}

function formatDateTime(dateStr?: string): string {
  if (!dateStr) return t("settings.scheduler.formatter.unset")
  const date = new Date(dateStr)
  return date.toLocaleString(locale.value, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function getStatusType(
  status: ExecutionStatus,
): "success" | "error" | "warning" | "info" | "default" {
  switch (status) {
    case "success":
      return "success"
    case "failed":
      return "error"
    case "running":
      return "info"
    case "stopped":
      return "warning"
    default:
      return "default"
  }
}

function getStatusIcon(status: ExecutionStatus): string {
  switch (status) {
    case "success":
      return "i-mdi-check-circle"
    case "failed":
      return "i-mdi-close-circle"
    case "running":
      return "i-mdi-loading"
    case "stopped":
      return "i-mdi-pause-circle"
    default:
      return "i-mdi-help-circle"
  }
}

function getStatusTextType(
  status: ExecutionStatus,
): "success" | "error" | "warning" | "info" | "default" {
  switch (status) {
    case "success":
      return "success"
    case "failed":
      return "error"
    case "running":
      return "info"
    case "stopped":
      return "warning"
    default:
      return "default"
  }
}

function getStatusLabel(status: ExecutionStatus): string {
  switch (status) {
    case "success":
      return t("settings.scheduler.status.success")
    case "failed":
      return t("settings.scheduler.status.failed")
    case "running":
      return t("settings.scheduler.status.running")
    case "stopped":
      return t("settings.scheduler.status.stopped")
    default:
      return t("common.unknown")
  }
}
</script>
<style scoped>
.n-anchor-link {
  line-height: 2;
}
</style>
