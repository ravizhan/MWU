<template>
  <div class="space-y-3 max-w-7xl mx-auto">
    <!-- Header stats row -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <NCard :bordered="false" content-style="padding: 16px">
        <div class="text-sm opacity-70">{{ t("panel.device") }}</div>
        <div class="text-2xl font-bold flex items-center gap-2">
          <div
            class="w-3 h-3 rounded-full"
            :style="{
              backgroundColor: indexStore.Connected ? 'green' : 'rgb(255,76,76)',
            }"
          />
          {{
            indexStore.Connected
              ? t("panel.connection.connected")
              : t("panel.connection.disconnected")
          }}
        </div>
      </NCard>
      <NCard :bordered="false" content-style="padding: 16px">
        <div class="text-sm opacity-70">{{ t("panel.taskList") }}</div>
        <div class="text-2xl font-bold">
          {{ selectedTaskCount }} {{ t("common.slash") }} {{ configStore.taskList.length }}
        </div>
      </NCard>
      <NCard :bordered="false" content-style="padding: 16px">
        <div class="text-sm opacity-70">{{ t("nav.routines") }}</div>
        <div class="text-2xl font-bold">
          {{ schedulerStore.enabledTasks.length }}
        </div>
      </NCard>
      <NCard :bordered="false" content-style="padding: 16px">
        <div class="text-sm opacity-70">{{ t("settings.about.version") }}</div>
        <div class="text-2xl font-bold">
          {{ settingsStore.settings.about.version || "-" }}
        </div>
      </NCard>
    </div>

    <!-- Main grid -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
      <!-- Left: Device + Resource -->
      <div class="space-y-3">
        <!-- Device Selection Card -->
        <NCard :bordered="false" content-style="padding: 16px">
          <h2 class="text-base font-semibold flex items-center gap-2 pb-3">
            <NIcon size="22">
              <PhonePortraitOutline />
            </NIcon>
            {{ t("panel.device") }}
          </h2>
          <PanelConnectionTabs
            mode="device"
            :selected-controller="deviceStore.selectedController"
            :selected-device-key="deviceStore.selectedDeviceKey"
            :play-cover-address="deviceStore.playCoverAddress"
            :controller-options="deviceStore.controllerOptions"
            :device-options="deviceStore.deviceOptions"
            :device-disabled="deviceStore.isDeviceResourceLocked"
            :resource-disabled="
              !deviceStore.selectedController || deviceStore.isDeviceResourceLocked
            "
            :selected-controller-disabled="deviceStore.selectedControllerDisabled"
            :is-play-cover="deviceStore.selectedControllerCapability?.type === 'PlayCover'"
            :resource="deviceStore.resource"
            :resources-list="deviceStore.resourcesList"
            @update:selected-controller="deviceStore.selectedController = $event"
            @update:selected-device-key="deviceStore.selectedDeviceKey = $event"
            @update:play-cover-address="deviceStore.playCoverAddress = $event"
            @update:resource="deviceStore.resource = $event"
            @controller-change="deviceStore.handleControllerChange()"
            @open-devices="deviceStore.openDevices()"
            @create-device="deviceStore.createCustomDevice($event)"
          />
        </NCard>

        <!-- Resource Selection Card -->
        <NCard :bordered="false" content-style="padding: 16px">
          <h2 class="text-base font-semibold flex items-center gap-2 pb-3">
            <NIcon size="22">
              <FolderOpenOutline />
            </NIcon>
            {{ t("panel.resource") }}
          </h2>
          <PanelConnectionTabs
            mode="resource"
            :resource="deviceStore.resource"
            :resources-list="deviceStore.resourcesList"
            :resource-disabled="
              !deviceStore.selectedController || deviceStore.isDeviceResourceLocked
            "
            @update:resource="deviceStore.resource = $event"
          />
        </NCard>
      </div>

      <!-- Right: Recipe Cards + Routine Health -->
      <div class="space-y-3 lg:col-span-2">
        <NCard :bordered="false" content-style="padding: 16px">
          <h2 class="text-base font-semibold flex items-center gap-2 pb-3">
            <NIcon size="22">
              <BookOutline />
            </NIcon>
            {{ t("panel.preset.title") }}
          </h2>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-2">
            <HomeRecipeCard
              v-for="preset in recipeCards"
              :key="preset.name"
              :preset="preset"
              @apply="applyPreset"
            />
          </div>
        </NCard>

        <!-- Routine Health -->
        <NCard :bordered="false" content-style="padding: 16px">
          <h2 class="text-base font-semibold flex items-center gap-2 pb-3">
            <NIcon size="22">
              <PulseOutline />
            </NIcon>
            {{ t("nav.routines") }}
          </h2>
          <RoutineHealthCard />
        </NCard>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"
import {
  BookOutline,
  FolderOpenOutline,
  PhonePortraitOutline,
  PulseOutline,
} from "@vicons/ionicons5"
import HomeRecipeCard from "@/components/home/HomeRecipeCard.vue"
import RoutineHealthCard from "@/components/home/RoutineHealthCard.vue"
import PanelConnectionTabs from "@/components/panel/PanelConnectionTabs.vue"
import {
  useIndexStore,
  useInterfaceStore,
  useTaskConfigStore,
  useSchedulerStore,
  useSettingsStore,
  useDeviceConnectionStore,
} from "@/stores"
import { resolveInterfaceText } from "@/utils/interface/content"

const { t, locale } = useI18n()
const router = useRouter()
const indexStore = useIndexStore()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const schedulerStore = useSchedulerStore()
const settingsStore = useSettingsStore()
const deviceStore = useDeviceConnectionStore()

const selectedTaskCount = computed(() => configStore.taskList.filter((task) => task.checked).length)

const recipeCards = computed(() => {
  return interfaceStore.getPresetList.map((preset) => {
    const taskCount = preset.task?.filter((t) => t.enabled !== false).length || 0
    return {
      name: preset.name,
      label: resolveInterfaceText(
        interfaceStore.interface,
        locale.value,
        preset.label,
        preset.name,
      ),
      description: preset.description || t("panel.preset.noDescription"),
      taskCount,
    }
  })
})

function applyPreset(name: string) {
  configStore.selectPreset(name)
  router.push({ name: "tasks" })
}

onMounted(() => {
  deviceStore.init()
  void schedulerStore.fetchTasks()
})

onUnmounted(() => {
  deviceStore.cleanup()
})
</script>
