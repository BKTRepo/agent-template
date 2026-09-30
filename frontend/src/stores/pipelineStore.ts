import { create } from 'zustand'
import { createSelectors } from '@/lib/createSelectors'
import { getPipelineStatus } from '@/api/pipeline'
import type { PipelineStatus } from '@/types/api'

interface PipelineState {
  status: PipelineStatus | null
  open: boolean
  polling: ReturnType<typeof setInterval> | null
  fetchStatus: () => Promise<void>
  startPolling: () => void
  stopPolling: () => void
  setOpen: (open: boolean) => void
}

const usePipelineStoreBase = create<PipelineState>()((set, get) => ({
  status: null,
  open: false,
  polling: null,

  fetchStatus: async () => {
    try {
      const s = await getPipelineStatus()
      set({ status: s })
    } catch {
      // retry next tick
    }
  },

  startPolling: () => {
    const { polling } = get()
    if (polling) return
    get().fetchStatus()
    const timer = setInterval(() => get().fetchStatus(), 2000)
    set({ polling: timer })
  },

  stopPolling: () => {
    const { polling } = get()
    if (polling) {
      clearInterval(polling)
      set({ polling: null })
    }
  },

  setOpen: (open) => {
    set({ open })
    if (open) get().startPolling()
    else get().stopPolling()
  },
}))

export const usePipelineStore = createSelectors(usePipelineStoreBase)
