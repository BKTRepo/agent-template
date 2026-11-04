import { create } from 'zustand'
import { canEditKnowledge, canViewKnowledge, type Actor } from '@/lib/access'
import { useAccessStore } from './accessStore'
import { getConversionStatus, getKnowledgeBase, knowledgeRequest, listKnowledgeBases, retryConversion, saveKnowledgeBase, type KnowledgeUpload } from '@/api/knowledge'
import type { KnowledgeBase } from '@/types/developer'

export type KnowledgeForm = Omit<KnowledgeBase, 'id' | 'updatedAt'> & { changeSummary?: string }
interface KnowledgeState {
  knowledgeBases: KnowledgeBase[]; loading: boolean; error: string
  reset: () => void; load: () => Promise<void>; replace: (item: KnowledgeBase) => void
  save: (form: KnowledgeForm, id?: string, uploads?: KnowledgeUpload[]) => Promise<KnowledgeBase>
  retry: (id: string) => Promise<void>; refreshProcessing: (signal?: AbortSignal) => Promise<void>
}
export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  knowledgeBases: [], loading: false, error: '',
  reset: () => set({ knowledgeBases: [], loading: false, error: '' }),
  replace: item => set(state => ({ knowledgeBases: state.knowledgeBases.some(row => row.id === item.id)
    ? state.knowledgeBases.map(row => row.id === item.id ? item : row) : [item, ...state.knowledgeBases] })),
  load: async () => {
    const actor = useAccessStore.getState().actor.id
    set({ loading: true, error: '' })
    try { const rows = await listKnowledgeBases(); if (useAccessStore.getState().actor.id === actor) set({ knowledgeBases: rows }) }
    catch (error) { if (useAccessStore.getState().actor.id === actor) set({ error: (error as Error).message }) }
    finally { if (useAccessStore.getState().actor.id === actor) set({ loading: false }) }
  },
  save: async (form, id, uploads = []) => {
    const actor = useAccessStore.getState().actor.id
    const result = await saveKnowledgeBase(form, uploads, id)
    if (useAccessStore.getState().actor.id !== actor) throw new Error('平台身份已切换，请重新加载知识库。')
    get().replace(result); return result
  },
  retry: async id => {
    const actor = useAccessStore.getState().actor.id
    const item = get().knowledgeBases.find(row => row.id === id)
    if (!item || !canEditKnowledge(item, useAccessStore.getState().actor)) throw new Error('没有重试权限。')
    const jobs = item.files.filter(file => file.conversionJobId && ['failed', 'delete_failed'].includes(file.conversionStatus || ''))
    for (const file of jobs) await retryConversion(file.conversionJobId!)
    if (!jobs.length) await knowledgeRequest('/knowledge-bases/retry', { method: 'POST', body: JSON.stringify({ kb_id: id }) })
    const updated = await getKnowledgeBase(id)
    if (useAccessStore.getState().actor.id === actor) get().replace(updated)
  },
  refreshProcessing: async signal => {
    const actor = useAccessStore.getState().actor.id
    const items = get().knowledgeBases.filter(row => row.processingStatus === '知识处理中')
    try {
      for (const item of items) {
        if (signal?.aborted || useAccessStore.getState().actor.id !== actor) return
        if (canEditKnowledge(item, useAccessStore.getState().actor)) {
          for (const file of item.files) if (file.conversionJobId) await getConversionStatus(file.conversionJobId, signal)
        }
        const current = await getKnowledgeBase(item.id, signal)
        if (!signal?.aborted && useAccessStore.getState().actor.id === actor) get().replace(current)
      }
      if (!signal?.aborted && useAccessStore.getState().actor.id === actor) set({ error: '' })
    } catch (error) { if (!signal?.aborted && useAccessStore.getState().actor.id === actor) set({ error: (error as Error).message }) }
  },
}))
export function filterKnowledgeBases(items: KnowledgeBase[], query: string, actor: Actor = useAccessStore.getState().actor) {
  return items.filter(row => canViewKnowledge(row, actor) && row.name.normalize('NFKC').toLowerCase().includes(query.trim().normalize('NFKC').toLowerCase()))
}
export function assertKnowledgeMounts(ids: string[], actor = useAccessStore.getState().actor) {
  for (const id of ids) { const item = useKnowledgeStore.getState().knowledgeBases.find(row => row.id === id)
    if (item && !canViewKnowledge(item, actor)) throw new Error('所选知识库不可见，请重新选择。') }
}
