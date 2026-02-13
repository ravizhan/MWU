<template>
  <n-card content-style="padding: 0;margin: 5px" hoverable>
    <n-tabs type="segment" animated>
      <n-tab-pane name="device" :tab="t('panel.device')">
        <n-flex class="pb-[12px]">
          <n-tree-select
            v-model:value="device"
            :placeholder="t('panel.selectDevice')"
            :options="devices_tree"
            :loading="loading"
            :override-default-node-click-behavior="override"
            remote
            indent="6"
            @click="get_device"
            class="max-w-80%"
          />
          <n-button strong secondary type="info" @click="connectDevices">{{
            t("panel.connect")
          }}</n-button>
        </n-flex>
      </n-tab-pane>
      <n-tab-pane name="resource" :tab="t('panel.resource')">
        <n-flex class="pb-[12px]">
          <n-select
            v-model:value="resource"
            :placeholder="t('panel.selectResource')"
            :options="resources_list"
            :loading="loading"
            remote
            @click="get_resource"
            class="max-w-80%"
          />
          <n-button strong secondary type="info" @click="post_resource">{{
            t("panel.confirm")
          }}</n-button>
        </n-flex>
      </n-tab-pane>
    </n-tabs>
  </n-card>
  <div class="col-name">{{ t("panel.taskList") }}</div>
  <n-card hoverable>
    <n-list hoverable bordered>
      <template v-if="scroll_show">
        <n-scrollbar trigger="none" class="max-h-75">
          <VueDraggable v-model="configStore.taskList">
            <n-list-item v-for="item in configStore.taskList" :key="item.id">
              <n-checkbox size="large" :label="item.name" v-model:checked="item.checked" />
              <template #suffix>
                <n-button quaternary circle @click="indexStore.SelectTask(item.id)">
                  <template #icon>
                    <n-icon><div class="i-mdi-cog-outline"></div></n-icon>
                  </template>
                </n-button>
              </template>
            </n-list-item>
          </VueDraggable>
        </n-scrollbar>
      </template>
      <template v-else>
        <VueDraggable v-model="configStore.taskList">
          <n-list-item v-for="item in configStore.taskList" :key="item.id">
            <n-checkbox size="large" :label="item.name" v-model:checked="item.checked" />
            <template #suffix>
              <n-button quaternary circle @click="indexStore.SelectTask(item.id)">
                <template #icon>
                  <n-icon><div class="i-mdi-cog-outline"></div></n-icon>
                </template>
              </n-button>
            </template>
          </n-list-item>
        </VueDraggable>
      </template>
    </n-list>
    <n-flex class="form-btn" justify="center">
      <n-button strong secondary type="info" size="large" @click="StartTask">{{
        t("panel.start")
      }}</n-button>
      <n-button strong secondary type="info" size="large" @click="stopTask">{{
        t("panel.stop")
      }}</n-button>
    </n-flex>
    <n-flex class="form-btn" justify="center">
      <n-button quaternary type="warning" size="small" @click="resetConfig">{{
        t("panel.resetConfig")
      }}</n-button>
    </n-flex>
  </n-card>
</template>
<script setup lang="ts">
import { watch, ref } from "vue"
import { useI18n } from "vue-i18n"
import {
  getDevices,
  postDevices,
  startTask,
  stopTask,
  type AdbDevice,
  type Win32Device,
  getResource,
  postResource,
} from "../script/api"
import { VueDraggable } from "vue-draggable-plus"
import { useUserConfigStore } from "../stores/userConfig"
import { useIndexStore } from "../stores"
import type { TreeSelectOverrideNodeClickBehavior } from "naive-ui"
import { useMessage, useDialog } from "naive-ui"
if (typeof window !== "undefined") {
  window.$message = useMessage()
}

const dialog = useDialog()
const { t } = useI18n()
const configStore = useUserConfigStore()
const indexStore = useIndexStore()
const scroll_show = ref(window.innerWidth > 768)
const device = ref<AdbDevice | Win32Device | null>(null)
const resource = ref<string | null>(null)
const devices_tree = ref<object[]>([])
const resources_list = ref<object[]>([])
const loading = ref(false)
const override: TreeSelectOverrideNodeClickBehavior = ({ option }) => {
  if (option.children) {
    return "toggleExpand"
  }
  return "default"
}

watch(
  () => configStore.taskList,
  (newList) => {
    if (newList.length) {
      indexStore.SelectTask(newList[0]!.id)
    }
  },
  { immediate: true },
)

watch(
  () => configStore.taskList,
  () => {
    if (configStore.configLoaded) {
      configStore.debouncedSave()
    }
  },
  { deep: true },
)

watch(
  () => configStore.options,
  () => {
    if (configStore.configLoaded) {
      configStore.debouncedSave()
    }
  },
  { deep: true },
)

function get_device() {
  devices_tree.value = [
    {
      label: "Adb",
      key: "Adb",
      children: [],
    },
    {
      label: "Win32",
      key: "Win32",
      children: [],
    },
  ]
  loading.value = true
  getDevices()
    .then((devices_data) => {
      for (const dev of devices_data.adb) {
        ;(devices_tree.value[0] as any).children.push({
          label: dev.name + " (" + dev.address + ")",
          key: dev,
        })
      }
      for (const dev of devices_data.win32) {
        ;(devices_tree.value[1] as any).children.push({
          label: dev.window_name + " (" + dev.class_name + ")",
          key: dev,
        })
      }
    })
    .then(() => {
      if ((devices_tree.value[0] as any).children.length === 0) {
        ;(devices_tree.value[0] as any).children.push({
          label: t("panel.noDevice"),
          key: "none",
          disabled: true,
        })
      }
      if ((devices_tree.value[1] as any).children.length === 0) {
        ;(devices_tree.value[1] as any).children.push({
          label: t("panel.noDevice"),
          key: "none",
          disabled: true,
        })
      }
      loading.value = false
    })
}

function connectDevices() {
  if (!device.value) {
    // @ts-ignore
    window.$message.error(t("panel.selectDevice"))
    return
  } else {
    postDevices(device.value).then((success) => {
      indexStore.setConnected(success)
    })
  }
}

function get_resource() {
  resources_list.value = []
  loading.value = true
  getResource().then((resource_data) => {
    for (const resource of resource_data) {
      resources_list.value?.push({
        label: resource,
        value: resource,
      })
    }
  })
  loading.value = false
}

function post_resource() {
  if (!resource.value) {
    // @ts-ignore
    window.$message.error(t("panel.selectResource"))
    return
  } else {
    postResource(resource.value)
  }
}

function StartTask() {
  const selectedTasks = configStore.taskList.filter((task) => task.checked).map((task) => task.id)
  if (selectedTasks.length === 0) {
    // @ts-ignore
    window.$message.error(t("panel.selectTask"))
    return
  }
  const options = configStore.buildOptionsForTasks(selectedTasks)
  startTask(selectedTasks, options)
}

function resetConfig() {
  dialog.warning({
    title: t("panel.resetConfig"),
    content: t("panel.resetConfigConfirm"),
    positiveText: t("common.confirm"),
    negativeText: t("common.cancel"),
    onPositiveClick: async () => {
      await configStore.resetConfig()
      // @ts-ignore
      window.$message.success(t("panel.configReset"))
    },
  })
}
</script>
<style scoped>
.list-group-item i {
  cursor: pointer;
}
.form-btn {
  text-align: center;
  padding-top: 5%;
}
</style>
