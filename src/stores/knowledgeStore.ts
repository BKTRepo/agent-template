import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { initialKnowledgeBases } from '@/mocks/knowledgeData'
import { assertApplications, canEditKnowledge, canViewKnowledge, demoActors, type Actor } from '@/lib/access'
import { nextVersion } from '@/lib/version'
import { useAccessStore } from './accessStore'
import type { KnowledgeBase } from '@/types/developer'

export type KnowledgeForm = Omit<KnowledgeBase, 'id' | 'updatedAt'> & { changeSummary?: string }
function normalizeKnowledge(item: KnowledgeBase): KnowledgeBase {
  const initial = initialKnowledgeBases.find(row => row.id === item.id)
  const firstMaintainer = item.history?.at(-1)?.maintainer
  const creator = demoActors.find(row => row.name === firstMaintainer)
  // 不再从历史团队成员关系推断所有权；无法识别创建者的历史记录保持只读。
  return { ...item, version: /^[vV]/.test(item.version) ? item.version.replace(/^[vV]/, 'V') : `V${item.version}`, applicationIds: item.applicationIds ?? ['*'], creatorId: item.creatorId ?? creator?.id ?? initial?.creatorId ?? 'legacy-unassigned', creatorName: item.creatorName ?? creator?.name ?? initial?.creatorName ?? '历史创建者未记录', maintainer: item.maintainer ?? initial?.maintainer ?? '历史维护人', processingStatus: item.processingStatus ?? '知识处理完成', history: item.history ?? [] }
}
export function migrateKnowledgeState(value: unknown) {
  const state = value as { knowledgeBases?: KnowledgeBase[] } | null
  return { knowledgeBases: (state?.knowledgeBases ?? initialKnowledgeBases).map(normalizeKnowledge) }
}
interface KnowledgeState {
  knowledgeBases: KnowledgeBase[]
  save: (form: KnowledgeForm, id?: string) => KnowledgeBase
  retry: (id: string, outcome?: 'success' | 'failure') => void
  finishProcessing: (id: string, jobId: string) => void
}
export const useKnowledgeStore = create<KnowledgeState>()(persist((set, get) => ({
  knowledgeBases: initialKnowledgeBases.map(normalizeKnowledge),
  save: (form, id) => {
    if (!form.name?.trim()) throw new Error('知识库名称不能为空')
    const actor = useAccessStore.getState().actor
    const previous = get().knowledgeBases.find(row => row.id === id)
    if (id && !previous) throw new Error('知识库不存在，请刷新后重试。')
    if (previous && !canEditKnowledge(previous, actor)) throw new Error('只有创建者本人可以编辑此知识库。')
    if (form.scope !== 'public' && form.scope !== 'team') throw new Error('请选择有效的可见范围。')
    assertApplications(form.applicationIds)
    if (form.applicationIds?.length !== 1) throw new Error('请选择一个所属应用。')
    if (!form.description?.trim()) throw new Error('请填写知识库描述。')
    if (!['通识类', '自定义'].includes(form.tag)) throw new Error('请选择知识库标签。')
    if (!form.files?.length) throw new Error('请至少上传一个知识库文件。')
    if (form.name.length > 128 || form.description.length > 500) throw new Error('知识库字段超过长度限制。')
    if (previous && !form.changeSummary?.trim()) throw new Error('请填写本次修改的变更摘要。')
    if ((form.changeSummary?.length ?? 0) > 1000) throw new Error('变更摘要最长 1000 个字符。')
    if (get().knowledgeBases.some(row => row.id !== id && row.name.trim().normalize('NFKC').toLowerCase() === form.name.trim().normalize('NFKC').toLowerCase())) throw new Error('知识库名称已存在')
    const changed = form.files.filter(file => !previous?.files.some(old => old.id === file.id && old.size === file.size && old.lastModified === file.lastModified && old.name === file.name)).map(file => file.id)
    const now = new Date().toISOString()
    const version = previous ? nextVersion(previous.version, 'V') : 'V1.0.0'
    const item: KnowledgeBase = {
      id: id ?? crypto.randomUUID(), name: form.name.trim(), version, description: form.description,
      tag: form.tag, scope: form.scope, team: previous?.team ?? '', creatorId: previous?.creatorId ?? actor.id, creatorName: previous?.creatorName ?? actor.name,
      applicationIds: [...form.applicationIds], vectorized: form.vectorized, model: form.model,
      files: form.files.map(file => ({ ...file })), updatedAt: now, maintainer: actor.name,
      processingStatus: changed.length ? '知识处理中' : previous?.processingStatus ?? '知识处理完成',
      processingJobId: changed.length ? crypto.randomUUID() : previous?.processingJobId,
      processingOutcome: changed.length ? form.processingOutcome ?? 'success' : previous?.processingOutcome,
      processedFileIds: changed.length ? changed : previous?.processedFileIds,
      history: [{ id: crypto.randomUUID(), version, summary: previous ? form.changeSummary!.trim() : '初始创建', maintainer: actor.name, updatedAt: now }, ...(previous?.history ?? [])],
    }
    set(state => ({ knowledgeBases: id ? state.knowledgeBases.map(row => row.id === id ? item : row) : [item, ...state.knowledgeBases] }))
    return item
  },
  retry: (id, outcome = 'success') => {
    const item = get().knowledgeBases.find(row => row.id === id)
    if (!item || !canEditKnowledge(item, useAccessStore.getState().actor)) throw new Error('没有重试此知识库的权限。')
    if (item.processingStatus !== '知识处理失败') throw new Error('只有知识处理失败的记录可以重试。')
    set(state => ({ knowledgeBases: state.knowledgeBases.map(row => row.id === id ? { ...row, processingStatus: '知识处理中', processingJobId: crypto.randomUUID(), processingOutcome: outcome, processedFileIds: row.processedFileIds?.length ? row.processedFileIds : row.files.map(file => file.id) } : row) }))
  },
  finishProcessing: (id, jobId) => set(state => ({ knowledgeBases: state.knowledgeBases.map(row => row.id === id && row.processingJobId === jobId && row.processingStatus === '知识处理中' ? { ...row, processingStatus: row.processingOutcome === 'failure' ? '知识处理失败' : '知识处理完成', processingJobId: undefined } : row) })),
}), { name: 'znfwdd-knowledge-v1', version: 3, migrate: migrateKnowledgeState }))

export function filterKnowledgeBases(items: KnowledgeBase[], query: string, actor: Actor = useAccessStore.getState().actor) {
  return items.filter(row => canViewKnowledge(row, actor) && row.name.normalize('NFKC').toLowerCase().includes(query.trim().normalize('NFKC').toLowerCase()))
}
export function assertKnowledgeMounts(ids: string[], actor = useAccessStore.getState().actor) {
  for (const id of ids) {
    const item = useKnowledgeStore.getState().knowledgeBases.find(row => row.id === id)
    if (item && !canViewKnowledge(item, actor)) throw new Error('所选知识库不在当前用户的可见范围，请重新选择。')
  }
}
