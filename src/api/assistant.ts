import type { AssistantPageContext } from '@/stores/assistantContextStore'
import { useAuthStore } from '@/stores/authStore'
import { hasSkillSession } from './skillSession'

export interface AssistantSkill { id: string; name: string; description?: string; input?: string; output?: string }
export interface ChatArtifactReference { artifactId: string; fileName: string; artifactType: string }
interface ArtifactReferenceResponse { artifact_id: string; file_name: string; artifact_type: string }
function artifactReferences(rows?: ArtifactReferenceResponse[]): ChatArtifactReference[] { return (rows ?? []).map(row => ({ artifactId: String(row.artifact_id), fileName: row.file_name, artifactType: row.artifact_type })) }
export type AssistantRole = 'user' | 'assistant'
export interface AssistantMessage { id: string; serverId?: number; role: AssistantRole; text: string; unread?: boolean; createdAt?: string; attachments?: string[]; artifacts?: ChatArtifactReference[]; taskId?: number; status?: 'generating' | 'completed' | 'stopped' | 'failed'; feedback?: 'up' | 'down'; feedbackReason?: string; context?: object }
export interface ChatConversation { id: string; title: string; favorite: boolean; generation: number; skills: number[]; knowledgeBases: number[]; model: string | null; unreadCount: number; createdAt: string; updatedAt: string }
export interface ChatModel { name: string; displayName: string }
export interface ChatModelHealth { model: string; status: 'healthy' | 'busy' | 'unavailable' | 'unconfigured' | 'checking'; latencyMs: number | null; checkedAt: string | null; stale: boolean; refreshing: boolean }
export interface ChatTask { taskId: number; status: 'pending' | 'running' | 'cancelling' | 'recovering' | 'success' | 'failed' | 'cancelled'; messageId: number; content: string; model: string; error: string | null; durationMs: number | null; artifacts: ChatArtifactReference[] }
export interface StartTask { taskId: number; messageId: number; status: ChatTask['status'] }
interface ApiResponse<T> { status: string; message?: string; detail?: string; data: T; total?: number }
export class AssistantApiError extends Error { constructor(message: string, public statusCode?: number) { super(message) } }

function query(params: Record<string, string | number | boolean | undefined | null>) { const values = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== '') values.set(key, String(value)) }); return values.toString() }
async function request<T>(path: string, options: RequestInit = {}): Promise<{ data: T; total?: number }> {
  if (!hasSkillSession()) throw new AssistantApiError('平台认证未配置，请检查登录状态或前端代理 token。')
  const token = useAuthStore.getState().session?.token
  let response: Response
  try { response = await fetch(path, { ...options, cache: 'no-store', headers: { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(token ? { token } : {}), ...options.headers } }) }
  catch (error) { if (options.signal?.aborted) throw error; throw new AssistantApiError('无法连接后端，请检查后端服务是否已经启动。') }
  if (response.status === 401) { useAuthStore.getState().setSession(null); throw new AssistantApiError('登录已失效，请重新登录平台。', 401) }
  const result = await response.json().catch(() => null) as ApiResponse<T> | null
  if (!response.ok || result?.status !== 'success') throw new AssistantApiError(result?.message || result?.detail || '对话服务请求失败。', response.status)
  return { data: result.data, total: result.total }
}
function toConversation(row: { id: string | number; title: string; favorite?: boolean; generation?: number; skills?: number[]; knowledge_bases?: number[]; model?: string | null; unread_count?: number; created_time?: string; updated_time?: string }): ChatConversation { return { id: String(row.id), title: row.title, favorite: !!row.favorite, generation: row.generation ?? 0, skills: row.skills ?? [], knowledgeBases: row.knowledge_bases ?? [], model: row.model ?? null, unreadCount: row.unread_count ?? 0, createdAt: row.created_time ?? '', updatedAt: row.updated_time ?? '' } }

export async function listChatConversations(search = '', favorite?: boolean) { const result = await request<Parameters<typeof toConversation>[0][]>(`/chat/conversation/list?${query({ search, favorite, offset: 0, limit: 100 })}`); return { items: result.data.map(toConversation), total: result.total ?? result.data.length } }
export async function createChatConversation(title = '新对话') { return toConversation((await request<Parameters<typeof toConversation>[0]>('/chat/conversation/create', { method: 'POST', body: JSON.stringify({ title }) })).data) }
export async function getChatConversation(conversationId: string) { return toConversation((await request<Parameters<typeof toConversation>[0]>(`/chat/conversation/detail?${query({ conversation_id: conversationId })}`)).data) }
export async function listChatMessages(conversationId: string) { const result = await request<{ id: number; role: AssistantRole; content: string; unread: boolean; created_time: string; artifacts?: ArtifactReferenceResponse[]; task_id?: number; task_status?: ChatTask['status']; feedback?: 'like' | 'dislike'; feedback_reason?: string; attachments?: string[]; context?: object }[]>(`/chat/message/list?${query({ conversation_id: conversationId, limit: 100 })}`); return result.data.map(row => ({ id: String(row.id), serverId: row.id, role: row.role, text: row.content, unread: row.unread, createdAt: row.created_time, artifacts: artifactReferences(row.artifacts), taskId: row.task_id, status: row.task_status ? taskDisplayStatus(row.task_status) : undefined, feedback: row.feedback === 'like' ? 'up' as const : row.feedback === 'dislike' ? 'down' as const : undefined, feedbackReason: row.feedback_reason, attachments: row.attachments, context: row.context })) }
export async function renameChatConversation(conversationId: string, title: string) { return toConversation((await request<Parameters<typeof toConversation>[0]>('/chat/conversation/rename', { method: 'POST', body: JSON.stringify({ conversation_id: conversationId, title }) })).data) }
export async function favoriteChatConversation(conversationId: string, favorite: boolean) { return toConversation((await request<Parameters<typeof toConversation>[0]>('/chat/conversation/favorite', { method: 'POST', body: JSON.stringify({ conversation_id: conversationId, favorite }) })).data) }
export async function saveChatResources(conversationId: string, resources: { skills: number[]; knowledgeBases: number[]; model: string | null }) { return toConversation((await request<Parameters<typeof toConversation>[0]>('/chat/conversation/resources', { method: 'POST', body: JSON.stringify({ conversation_id: conversationId, skills: resources.skills, knowledge_bases: resources.knowledgeBases, model: resources.model }) })).data) }
export async function readChatConversation(conversationId: string) { await request('/chat/conversation/read', { method: 'POST', body: JSON.stringify({ conversation_id: conversationId }) }) }
export async function clearChatConversation(conversationId: string) { return toConversation((await request<Parameters<typeof toConversation>[0]>('/chat/conversation/clear', { method: 'POST', body: JSON.stringify({ conversation_id: conversationId }) })).data) }
export async function deleteChatConversation(conversationId: string) { await request('/chat/conversation/delete', { method: 'POST', body: JSON.stringify({ conversation_id: conversationId }) }) }
export async function listChatModels() { const result = await request<{ name: string; display_name: string }[]>('/chat/models'); return result.data.map(row => ({ name: row.name, displayName: row.display_name })) }
export async function listChatModelHealth() {
  const result = await request<{ model: string; status: ChatModelHealth['status']; latency_ms: number | null; checked_at: string | null; stale: boolean; refreshing: boolean }[]>('/chat/models/health')
  return result.data.map(row => ({ model: row.model, status: row.status, latencyMs: row.latency_ms, checkedAt: row.checked_at, stale: row.stale, refreshing: row.refreshing }))
}
function toStartTask(row: { task_id: number; message_id: number; status: ChatTask['status'] }): StartTask { return { taskId: row.task_id, messageId: row.message_id, status: row.status } }
export async function sendChatMessage(conversationId: string, content: string, model: string | null, files: File[], context?: AssistantPageContext, sourceTaskId?: number) {
  if (!content.trim() && !files.length) throw new AssistantApiError('请输入需求或上传本次对话文件。')
  if (!files.length) return toStartTask((await request<{ task_id: number; message_id: number; status: ChatTask['status'] }>('/chat/send', { method: 'POST', body: JSON.stringify({ conversation_id: conversationId, content: content.trim(), model, context, source_task_id: sourceTaskId }) })).data)
  const form = new FormData(); form.append('conversation_id', conversationId); form.append('content', content.trim()); if (model) form.append('model', model); if (context) form.append('context', JSON.stringify(context)); if (sourceTaskId) form.append('source_task_id', String(sourceTaskId)); files.forEach(file => form.append('files', file, file.name))
  return toStartTask((await request<{ task_id: number; message_id: number; status: ChatTask['status'] }>('/chat/send-with-files', { method: 'POST', body: form })).data)
}
function toTask(row: { artifacts?: ArtifactReferenceResponse[]; task_id: number; status: ChatTask['status']; message_id: number; content: string; model: string; error: string | null; duration_ms: number | null }): ChatTask { return { taskId: row.task_id, status: row.status, messageId: row.message_id, content: row.content, model: row.model, error: row.error, durationMs: row.duration_ms, artifacts: artifactReferences(row.artifacts) } }
export async function getChatTask(taskId: number) { return toTask((await request<{ task_id: number; status: ChatTask['status']; message_id: number; content: string; model: string; error: string | null; duration_ms: number | null }>(`/chat/task?${query({ task_id: taskId })}`)).data) }
export async function stopChatTask(taskId: number) { return toTask((await request<{ task_id: number; status: ChatTask['status']; message_id: number; content: string; model: string; error: string | null; duration_ms: number | null }>('/chat/stop', { method: 'POST', body: JSON.stringify({ task_id: taskId }) })).data) }
export async function retryChatTask(taskId: number, files: File[] = []) { if (!files.length) return toStartTask((await request<{ task_id: number; message_id: number; status: ChatTask['status'] }>('/chat/retry', { method: 'POST', body: JSON.stringify({ task_id: taskId }) })).data); const form = new FormData(); form.append('task_id', String(taskId)); files.forEach(file => form.append('files', file, file.name)); return toStartTask((await request<{ task_id: number; message_id: number; status: ChatTask['status'] }>('/chat/retry-with-files', { method: 'POST', body: form })).data) }
export async function sendChatFeedback(messageId: number, rating: 'like' | 'dislike', reason?: string) { return (await request<{ id: number; rating: 'like' | 'dislike'; reason?: string | null }>('/chat/feedback', { method: 'POST', body: JSON.stringify({ message_id: messageId, rating, reason }) })).data }

/** /chat/events 需携带 token，故使用 fetch 解码 SSE，而非 EventSource。 */
export async function streamChatTask(taskId: number, onUpdate: (task: ChatTask) => void, signal: AbortSignal) {
  if (!hasSkillSession()) throw new AssistantApiError('平台认证未配置，请检查登录状态或前端代理 token。')
  const token = useAuthStore.getState().session?.token
  let response: Response
  try { response = await fetch(`/chat/events?${query({ task_id: taskId })}`, { cache: 'no-store', signal, headers: token ? { token } : {} }) } catch (error) { if (signal.aborted) throw error; throw new AssistantApiError('无法建立对话流，请检查后端服务。') }
  if (!response.ok || !response.body) { const result = await response.json().catch(() => null) as ApiResponse<unknown> | null; throw new AssistantApiError(result?.message || result?.detail || '无法建立对话流。', response.status) }
  const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = ''
  const handle = (block: string) => { const text = block.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n'); if (!text || text === '{}') return; const row = JSON.parse(text) as { task_id: number; status: ChatTask['status']; message_id: number; content: string; model: string; error: string | null; duration_ms: number | null }; onUpdate(toTask(row)) }
  try { while (true) { const { done, value } = await reader.read(); buffer += decoder.decode(value, { stream: !done }); const blocks = buffer.split(/\r?\n\r?\n/); buffer = blocks.pop() ?? ''; blocks.forEach(handle); if (done) break } if (buffer.trim()) handle(buffer) } finally { reader.releaseLock() }
}

export const chatFileExtensions = ['.pdf', '.docx', '.xlsx', '.txt', '.md', '.json', '.csv', '.py', '.js', '.sql', '.sh', '.bash', '.png', '.jpg', '.jpeg']
export const chatFileLimits = { maxFileBytes: 20 * 1024 * 1024, maxFiles: 10, maxTotalBytes: 100 * 1024 * 1024 }

export const taskDisplayStatus = (status: ChatTask['status']) => status === 'success' ? 'completed' as const : status === 'failed' ? 'failed' as const : status === 'cancelled' ? 'stopped' as const : 'generating' as const
export async function listChatTasks() {
  const result = await request<(Parameters<typeof toTask>[0] & { conversation_id: string })[]>('/chat/tasks')
  return result.data.map(row => ({ ...toTask(row), conversationId: row.conversation_id }))
}
export async function deleteAllChatConversations() { await request('/chat/conversation/delete-all', { method: 'POST', body: '{}' }) }
