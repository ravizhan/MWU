import { defineStore } from "pinia"
import { confirmFocusModal, stopTask } from "@/services/api"
import type { FocusModal, RealtimeEventLevel } from "@/types/realtimeModel"

interface FocusDialog {
  id: number
  message: string
  level: RealtimeEventLevel
}

interface FocusState {
  dialogs: FocusDialog[]
  modals: FocusModal[]
  nextDialogId: number
  busy: boolean
}

export interface FocusEventReceiver {
  enqueueDialog(message: string, level: RealtimeEventLevel): void
  replaceModals(modals: FocusModal[]): void
}

export const useFocusStore = defineStore("focus", {
  state: (): FocusState => ({
    dialogs: [],
    modals: [],
    nextDialogId: 0,
    busy: false,
  }),
  getters: {
    active(state): ({ kind: "dialog" } & FocusDialog) | ({ kind: "modal" } & FocusModal) | null {
      const modal = state.modals[0]
      if (modal) return { kind: "modal", ...modal }
      const dialog = state.dialogs[0]
      return dialog ? { kind: "dialog", ...dialog } : null
    },
  },
  actions: {
    enqueueDialog(message: string, level: RealtimeEventLevel): void {
      this.dialogs.push({ id: this.nextDialogId++, message, level })
    },
    dismissDialog(id: number): void {
      this.dialogs = this.dialogs.filter((dialog) => dialog.id !== id)
    },
    replaceModals(modals: FocusModal[]): void {
      this.modals = modals
    },
    async confirmModal(id: string): Promise<boolean> {
      this.busy = true
      const success = await confirmFocusModal(id)
      this.busy = false
      return success
    },
    async stopTaskFromModal(): Promise<boolean> {
      this.busy = true
      const success = await stopTask()
      this.busy = false
      return success
    },
  },
})
