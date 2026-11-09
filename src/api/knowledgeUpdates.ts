import { request } from './developerCenter'

export interface KnowledgeUpdateSummary {
  unread_skill_count: number
  unread_update_count: number
  skill_counts: Record<string, number>
}
export interface KnowledgeUpdate {
  notification_id: number; knowledge_base_id: number; knowledge_name: string
  latest_revision: number; read_revision: number; from_version: string; latest_version: string
  change_summary: string; processing_status: 'processing' | 'completed' | 'failed'; updated_at: string
}
export interface KnowledgeUpdates {
  skill_id: number; knowledge_update_count: number; items: KnowledgeUpdate[]
}
export function getKnowledgeUpdateSummary(signal?: AbortSignal) {
  return request<KnowledgeUpdateSummary>('/skills/developer/get-knowledge-update-summary', { signal })
}
export function getKnowledgeUpdates(skillId: string, signal?: AbortSignal) {
  return request<KnowledgeUpdates>(`/skills/developer/get-knowledge-updates?${new URLSearchParams({ skill_id: skillId })}`, { signal })
}
export function markKnowledgeUpdatesRead(skillId: string, items: KnowledgeUpdate[]) {
  return request<KnowledgeUpdates & { summary: KnowledgeUpdateSummary }>('/skills/developer/mark-knowledge-updates-read', {
    method: 'POST', body: JSON.stringify({ skill_id: Number(skillId),
      items: items.map(item => ({ notification_id: item.notification_id, seen_revision: item.latest_revision })) }),
  })
}
