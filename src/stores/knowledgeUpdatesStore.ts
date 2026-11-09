import { create } from 'zustand'
import { getKnowledgeUpdateSummary, type KnowledgeUpdateSummary } from '@/api/knowledgeUpdates'
import { useAuthStore } from './authStore'

interface UpdateState {
  summary: KnowledgeUpdateSummary | null
  reset: () => void
  refresh: () => Promise<void>
  apply: (summary: KnowledgeUpdateSummary, token: string) => void
}
let sequence = 0
export const useKnowledgeUpdatesStore = create<UpdateState>((set) => ({
  summary: null,
  reset: () => { sequence++; set({ summary: null }) },
  apply: (summary, token) => {
    if (useAuthStore.getState().session?.token === token) { sequence++; set({ summary }) }
  },
  refresh: async () => {
    const token = useAuthStore.getState().session?.token, request = ++sequence
    if (!token) return
    const summary = await getKnowledgeUpdateSummary()
    if (request === sequence && useAuthStore.getState().session?.token === token) set({ summary })
  },
}))
