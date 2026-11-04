import { useAuthStore } from '@/stores/authStore'
import { useAccessStore } from '@/stores/accessStore'
import { hasSkillSession, skillAccount } from './skillSession'
import type { KnowledgeBase, KnowledgeBaseOption } from '@/types/developer'

export interface KnowledgeUpload { id: string; file: File }
export interface ConversionJob { job_id?: string; id?: string; status: string; summary?: string; error_msg?: string }
interface ServerDocument { id: string | number; filename: string; file_size: number; status: string; updated_time: string; conversion_job_id?: string; conversion_status?: string; error_message?: string }
interface ServerKnowledge {
  id: string | number; knowledge_name: string; description: string; tag: string; application: string; version: string
  user_id: number; creator_login_name?: string; creator_name?: string; maintainer: string; is_public: boolean; can_edit: boolean
  status: string; reference_count: number; updated_time: string; documents: ServerDocument[]
  history: { version: string; maintainer: string; change_summary: string; created_at: string }[]
}
export async function knowledgeRequest<T>(path: string, options: RequestInit = {}): Promise<{ data: T; total?: number }> {
  if (!hasSkillSession()) throw new Error('请先登录平台后再使用知识库。')
  const token = useAuthStore.getState().session?.token
  const response = await fetch(path, { ...options, cache: 'no-store', headers: {
    ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(token ? { token } : {}), ...options.headers,
  } })
  if (response.status === 401) { useAuthStore.getState().setSession(null); throw new Error('登录已失效，请重新登录平台。') }
  const result = await response.json().catch(() => null)
  if (!response.ok || result?.status !== 'success') throw new Error(result?.message || result?.detail || '知识库请求失败，请检查平台登录和服务连接。')
  return result
}
export function toKnowledge(row: ServerKnowledge): KnowledgeBase {
  return { id: String(row.id), name: row.knowledge_name, description: row.description || '', version: row.version,
    tag: ({ general: '通识类', custom: '自定义', dependency: '依赖类' } as Record<string, string>)[row.tag] || '',
    team: '', scope: row.is_public ? 'public' : 'team', applicationIds: row.application ? [row.application] : [],
    source: 'backend', creatorId: row.creator_login_name || String(row.user_id), creatorName: row.creator_name || row.creator_login_name || String(row.user_id),
    canEdit: row.can_edit, referenceCount: row.reference_count, maintainer: row.maintainer, updatedAt: row.updated_time,
    vectorized: row.status === 'completed', model: '',
    processingStatus: row.status === 'completed' ? '知识处理完成' : row.status === 'failed' ? '知识处理失败' : '知识处理中',
    files: (row.documents || []).map(doc => ({ id: String(doc.id), name: doc.filename, size: doc.file_size,
      lastModified: Date.parse(doc.updated_time) || 0, conversionJobId: doc.conversion_job_id,
      conversionStatus: doc.conversion_status, errorMessage: doc.error_message })),
    history: [...(row.history || [])].reverse().map((entry, i) => ({ id: `${row.id}:${entry.version}:${i}`,
      version: entry.version, summary: entry.change_summary, maintainer: entry.maintainer, updatedAt: entry.created_at })),
  }
}
export async function listKnowledgeBases(search = '', signal?: AbortSignal) {
  const items: KnowledgeBase[] = []
  let total = 0
  do {
    const result = await knowledgeRequest<ServerKnowledge[]>(`/knowledge-bases/list?${new URLSearchParams({ search: search.trim(), offset: String(items.length), limit: '100' })}`, { signal })
    items.push(...result.data.map(toKnowledge)); total = result.total ?? items.length
    if (!result.data.length) break
  } while (items.length < total)
  return items
}
export async function getKnowledgeBase(id: string, signal?: AbortSignal) {
  return toKnowledge((await knowledgeRequest<ServerKnowledge>(`/knowledge-bases/detail?${new URLSearchParams({ kb_id: id })}`, { signal })).data)
}
export async function submitConversion(file: File): Promise<ConversionJob> {
  const data = new FormData(); data.append('file', file, file.name)
  const result = (await knowledgeRequest<ConversionJob>('/api/convert', { method: 'POST', body: data })).data
  if (!result.job_id) throw new Error('文档处理服务未返回 job_id，未创建本地模拟任务。')
  return result
}
export async function getConversionStatus(jobId: string, signal?: AbortSignal) {
  return (await knowledgeRequest<ConversionJob>(`/api/convert/status?${new URLSearchParams({ job_id: jobId })}`, { signal })).data
}
export async function retryConversion(jobId: string) {
  return (await knowledgeRequest<ConversionJob>('/api/convert/retry', { method: 'POST', body: JSON.stringify({ job_id: jobId }) })).data
}
// Successful uploads survive a metadata-save retry and are isolated by platform account.
const submissions = new Map<string, Promise<ConversionJob>>()
export async function saveKnowledgeBase(form: Omit<KnowledgeBase, 'id' | 'updatedAt'> & { changeSummary?: string }, uploads: KnowledgeUpload[], id?: string) {
  const account = skillAccount(), actor = useAccessStore.getState().actor.id
  const checkIdentity = () => { if (skillAccount() !== account || useAccessStore.getState().actor.id !== actor) throw new Error('平台身份已切换，已停止提交文档，请重新打开知识库。') }
  const keys: string[] = [], jobIds: string[] = []
  for (const upload of uploads.filter(row => !id && form.files.some(file => file.id === row.id))) {
    checkIdentity()
    const key = `${account}:${upload.id}`; keys.push(key)
    let submitted = submissions.get(key)
    if (!submitted) { submitted = submitConversion(upload.file); submissions.set(key, submitted); submitted.catch(() => submissions.delete(key)) }
    jobIds.push((await submitted).job_id!)
  }
  checkIdentity()
  const newIds = new Set(uploads.map(row => row.id))
  const data = new FormData()
  if (id) for (const upload of uploads.filter(row => form.files.some(file => file.id === row.id))) data.append('files', upload.file, upload.file.name)
  data.append('source', JSON.stringify({ knowledge_name: form.name.trim(), description: form.description,
    tag: ({ '通识类': 'general', '依赖类': 'dependency', '自定义': 'custom' } as Record<string, string>)[form.tag] || '',
    application: form.applicationIds?.[0] || '', is_public: form.scope === 'public',
    change_summary: form.changeSummary || '', ...(id ? { expected_version: form.version,
      retained_document_ids: form.files.filter(file => !newIds.has(file.id)).map(file => file.id) } : {}),
    conversion_job_ids: jobIds }))
  if (id) data.append('kb_id', id)
  const result = toKnowledge((await knowledgeRequest<ServerKnowledge>(id ? '/knowledge-bases/save' : '/knowledge-bases/create', { method: 'POST', body: data })).data)
  keys.forEach(key => submissions.delete(key))
  return result
}
export async function downloadKnowledgeFile(kbId: string, documentId: string) {
  const token = useAuthStore.getState().session?.token
  const response = await fetch(`/knowledge-bases/documents/download?${new URLSearchParams({ kb_id: kbId, doc_id: documentId })}`, { headers: token ? { token } : {}, cache: 'no-store' })
  if (!response.ok || /json|text\/html/i.test(response.headers.get('Content-Type') || '')) throw new Error('原文件下载失败，请检查访问权限。')
  return response.blob()
}
export async function searchKnowledgeBases(search: string, _team: string, signal: AbortSignal): Promise<{ items: KnowledgeBaseOption[]; demo: boolean }> {
  return { demo: false, items: (await listKnowledgeBases(search, signal)).filter(row => row.processingStatus === '知识处理完成').map(row => ({
    id: row.id, name: row.name, description: row.description, scope: row.scope === 'public' ? '全平台' : '仅本人', source: 'backend',
  })) }
}
