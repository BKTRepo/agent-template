import { create } from 'zustand'
import { canEditKnowledge, canViewKnowledge, canRetryKnowledge, type Actor } from '@/lib/access'
import { useAuthStore } from './authStore'
import { useAccessStore } from './accessStore'
import { getConversionStatus, getKnowledgeBase, knowledgeRequest, listKnowledgeBasesPage, KNOWLEDGE_PAGE_SIZE, retryConversion, saveKnowledgeBase, type KnowledgeUpload } from '@/api/knowledge'
import type { KnowledgeBase } from '@/types/developer'

export type KnowledgeForm = Omit<KnowledgeBase, 'id' | 'updatedAt'> & { changeSummary?: string }
const retryRequests = new Map<string, Promise<void>>()
let loadSequence = 0
interface KnowledgeState {
  knowledgeBases: KnowledgeBase[]; loading: boolean; error: string; retryingIds: string[]
  page: number; pageSize: number; total: number; pages: number; search: string
  reset: () => void; load: (page?: number, search?: string) => Promise<void>; replace: (item: KnowledgeBase) => void
  save: (form: KnowledgeForm, id?: string, uploads?: KnowledgeUpload[]) => Promise<KnowledgeBase>
  retry: (id: string) => Promise<void>; refreshProcessing: (signal?: AbortSignal) => Promise<void>
}
export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  knowledgeBases: [], loading: false, error: '', retryingIds: [],
  page: 1, pageSize: KNOWLEDGE_PAGE_SIZE, total: 0, pages: 1, search: '',
  reset: () => { loadSequence++; set({ knowledgeBases: [], loading: false, error: '', retryingIds: [], page: 1, pageSize: KNOWLEDGE_PAGE_SIZE, total: 0, pages: 1, search: '' }) },
  replace: item => set(state => ({ knowledgeBases: state.knowledgeBases.some(row => row.id === item.id)
    ? state.knowledgeBases.map(row => row.id === item.id ? item : row) : [item, ...state.knowledgeBases].slice(0, KNOWLEDGE_PAGE_SIZE) })),
  load: async (page = get().page, search = get().search) => {
    const actor = useAccessStore.getState().actor.id
    const token = useAuthStore.getState().session?.token, sequence = ++loadSequence
    const current = () => sequence === loadSequence && useAccessStore.getState().actor.id === actor && useAuthStore.getState().session?.token === token
    set({ loading: true, error: '' })
    try {
      let result = await listKnowledgeBasesPage(page, search)
      if (!current()) return
      if (result.page > result.pages) result = await listKnowledgeBasesPage(result.pages, search)
      if (current()) set({ knowledgeBases: result.items, page: result.page, total: result.total, pages: result.pages, search: search.trim() })
    }
    catch (error) { if (current()) set({ error: (error as Error).message }) }
    finally { if (current()) set({ loading: false }) }
  },
  save: async (form, id, uploads = []) => {
    const actor = useAccessStore.getState().actor.id
    const result = await saveKnowledgeBase(form, uploads, id)
    if (useAccessStore.getState().actor.id !== actor) throw new Error('平台身份已切换，请重新加载知识库。')
    await get().load(id ? get().page : 1, id ? get().search : '')
    return result
  },
  retry: id => {
    const actor = useAccessStore.getState().actor.id
    const token = useAuthStore.getState().session?.token
    const current = () => useAccessStore.getState().actor.id === actor && useAuthStore.getState().session?.token === token
    const key = JSON.stringify([actor, token, id])
    const pending = retryRequests.get(key)
    if (pending) return pending
    const operation = async () => {
      const item = get().knowledgeBases.find(row => row.id === id)
      if (!item || !canRetryKnowledge(item, useAccessStore.getState().actor)) throw new Error('仅创建者可重试失败的知识库。')
      set(state => ({ retryingIds: [...state.retryingIds, id] }))
      const jobs = item.files.filter(file => file.conversionJobId && ['failed', 'delete_failed'].includes(file.conversionStatus || ''))
      const errors: string[] = []
      let submitted = 0
      const checkIdentity = () => { if (!current()) throw new Error('登录用户已切换，已停止提交重试。') }
      for (const file of jobs) {
        checkIdentity()
        try { await retryConversion(file.conversionJobId!); submitted++ }
        catch (error) { errors.push(`${file.name}：${(error as Error).message}`) }
      }
      if (!jobs.length) {
        checkIdentity()
        try { await knowledgeRequest('/knowledge-bases/retry', { method: 'POST', body: JSON.stringify({ kb_id: Number(id) }) }); submitted++ }
        catch (error) { errors.push((error as Error).message) }
      }
      // Refresh partial successes too, so the next attempt only retries remaining failures.
      if (current()) {
        try { const updated = await getKnowledgeBase(id); if (current() && get().knowledgeBases.some(row => row.id === id)) get().replace(updated) }
        catch (error) { errors.push(`进度刷新失败：${(error as Error).message}`) }
      }
      if (errors.length) throw new Error(`${submitted ? '部分操作已提交；' : '重试失败；'}${errors.join('；')}`)
    }
    const request = operation().finally(() => {
      retryRequests.delete(key)
      if (current()) set(state => ({ retryingIds: state.retryingIds.filter(value => value !== id) }))
    })
    retryRequests.set(key, request)
    return request
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
        if (!signal?.aborted && useAccessStore.getState().actor.id === actor && get().knowledgeBases.some(row => row.id === item.id)) get().replace(current)
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
