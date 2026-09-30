import { apiClient } from './client'
import type { AnswerFeedbackStatus, Conversation, ConversationMessage, ConversationSearchMatch } from '@/types/api'

/** 获取会话列表（按最近活跃倒序） */
export async function listConversations(): Promise<Conversation[]> {
  const { data } = await apiClient.get<{ items?: Conversation[]; total?: number } | Conversation[]>('/conversations')
  return Array.isArray(data) ? data : (data?.items ?? [])
}

/** 新建会话 */
export async function createConversation(title?: string): Promise<Conversation> {
  const { data } = await apiClient.post<Conversation>('/conversations', { title })
  return data
}

/** 读取会话历史消息（时间升序） */
export async function getConversationMessages(id: number): Promise<ConversationMessage[]> {
  const { data } = await apiClient.get<{ items?: ConversationMessage[]; total?: number } | ConversationMessage[]>(`/conversations/${id}/messages`)
  return Array.isArray(data) ? data : (data?.items ?? [])
}

/** 重命名会话 */
export async function renameConversation(id: number, title: string): Promise<Conversation> {
  const { data } = await apiClient.patch<Conversation>(`/conversations/${id}`, { title })
  return data
}

/** 置顶 / 取消置顶会话 */
export async function setConversationPin(id: number, pinned: boolean): Promise<Conversation> {
  const { data } = await apiClient.patch<Conversation>(`/conversations/${id}/pin`, { pinned })
  return data
}

/** 删除会话 */
export async function deleteConversation(id: number): Promise<void> {
  await apiClient.delete(`/conversations/${id}`)
}

/** 按关键词搜索会话内容（AI 回答）, 返回命中记录列表 */
export async function searchConversations(q: string): Promise<ConversationSearchMatch[]> {
  const { data } = await apiClient.get<ConversationSearchMatch[]>('/conversations/search', { params: { q } })
  return data ?? []
}

/** 停止会话中某条仍在生成的消息（保留已生成内容） */
export async function stopMessageGeneration(conversationId: number, messageIndex: number): Promise<void> {
  await apiClient.post(`/conversations/${conversationId}/messages/${messageIndex}/stop`)
}

/** 查询回答采纳状态 */
export async function getAnswerFeedback(conversationId: number, messageIndex: number): Promise<AnswerFeedbackStatus> {
  const { data } = await apiClient.get<AnswerFeedbackStatus>(
    `/conversations/${conversationId}/messages/${messageIndex}/feedback`,
  )
  return data
}

/** 采纳或取消采纳回答；快照由后端从服务端消息和检索详情生成 */
export async function setAnswerFeedback(
  conversationId: number,
  messageIndex: number,
  action: 'accepted' | 'revoked',
): Promise<AnswerFeedbackStatus> {
  const { data } = await apiClient.put<AnswerFeedbackStatus>(
    `/conversations/${conversationId}/messages/${messageIndex}/feedback`,
    { action },
  )
  return data
}
