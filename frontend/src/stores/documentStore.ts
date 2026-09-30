import { create } from 'zustand'
import { createSelectors } from '@/lib/createSelectors'
import type { Document } from '@/types/api'
import { listDocuments, getConvertStatus } from '@/api/documents'
import { POLL_INTERVAL } from '@/lib/constants'
import { toast } from '@/lib/toast'

const ACTIVE_STATUSES = new Set([
  'splitting', 'pending', 'parsing', 'terminology', 'analyzing', 'chunking', 'embedding',
])

interface DocumentState {
  documents: Document[]
  loading: boolean
  /** 是否正在提交上传（串行上传: 上传期间禁止再次上传） */
  uploading: boolean
  pollTimers: Record<string, ReturnType<typeof setInterval>>
  selectedIds: Set<string>

  fetchDocuments: () => Promise<void>
  updateDocument: (id: string, updates: Partial<Document>) => void
  removeDocuments: (ids: string[]) => void
  addDocument: (doc: Document) => void
  setUploading: (uploading: boolean) => void
  toggleSelect: (id: string) => void
  selectAll: () => void
  deselectAll: () => void
  startPolling: (jobId: string) => void
  stopPolling: (jobId: string) => void
  stopAllPolling: () => void
  resumePendingPolls: () => void
  hasSelection: () => boolean
  hasActiveJobs: () => boolean
}

const useDocumentStoreBase = create<DocumentState>()((set, get) => ({
  documents: [],
  loading: true,
  uploading: false,
  pollTimers: {},
  selectedIds: new Set<string>(),

  fetchDocuments: async () => {
    set({ loading: true })
    try {
      const { selectedIds } = get()
      const data = await listDocuments()
      set({ documents: data, loading: false })
      get().resumePendingPolls()
    } catch {
      set({ loading: false })
    }
  },

  updateDocument: (id, updates) =>
    set((s) => ({
      documents: s.documents.map((d) =>
        d.id === id ? { ...d, ...updates } : d,
      ),
    })),

  removeDocuments: (ids) => {
    const idSet = new Set(ids)
    set((s) => ({
      documents: s.documents.filter((d) => !idSet.has(d.id)),
      selectedIds: new Set([...s.selectedIds].filter((id) => !idSet.has(id))),
    }))
  },

  addDocument: (doc) =>
    set((s) => ({ documents: [doc, ...s.documents] })),

  setUploading: (uploading) => set({ uploading }),

  toggleSelect: (id) =>
    set((s) => {
      const next = new Set(s.selectedIds)
      next.has(id) ? next.delete(id) : next.add(id)
      return { selectedIds: next }
    }),

  selectAll: () =>
    set((s) => ({
      selectedIds: new Set(s.documents.map((d) => d.id)),
    })),

  deselectAll: () => set({ selectedIds: new Set() }),

  startPolling: (jobId) => {
    const { pollTimers } = get()
    if (pollTimers[jobId]) return
    const timer = setInterval(async () => {
      try {
        // 取本轮轮询前的快照: 用于识别"由更新中 → 完成"的跳变, 触发更新完成提示
        const prev = get().documents.find((d) => d.id === jobId)
        const status = await getConvertStatus(jobId)
        get().updateDocument(jobId, status)
        if (
          !ACTIVE_STATUSES.has(status.status)
        ) {
          get().stopPolling(jobId)
          if (prev?.is_updating && status.status === 'complete') {
            const last = status.update_history?.[status.update_history.length - 1]
            const stats = last && last.reused != null && last.embedded != null
              ? `（复用 ${last.reused} / 新嵌入 ${last.embedded}）`
              : ''
            toast.success(`增量更新完成: ${status.filename}${stats}`, { timeout: 3000 })
          }
        }
      } catch {
        // retry on next interval
      }
    }, POLL_INTERVAL)
    set((s) => ({ pollTimers: { ...s.pollTimers, [jobId]: timer } }))
  },

  stopPolling: (jobId) => {
    const { pollTimers } = get()
    if (pollTimers[jobId]) {
      clearInterval(pollTimers[jobId])
      const next = { ...pollTimers }
      delete next[jobId]
      set({ pollTimers: next })
    }
  },

  stopAllPolling: () => {
    const { pollTimers } = get()
    Object.values(pollTimers).forEach(clearInterval)
    set({ pollTimers: {} })
  },

  resumePendingPolls: () => {
    const { documents } = get()
    documents.forEach((d) => {
      if (ACTIVE_STATUSES.has(d.status)) {
        get().startPolling(d.id)
      }
    })
  },

  hasSelection: () => get().selectedIds.size > 0,
  hasActiveJobs: () =>
    get().documents.some((d) => ACTIVE_STATUSES.has(d.status)),
}))

export const useDocumentStore = createSelectors(useDocumentStoreBase)
