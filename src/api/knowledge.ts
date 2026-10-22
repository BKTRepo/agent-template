import { useAuthStore } from '@/stores/authStore'
import type { KnowledgeBaseOption } from '@/types/developer'

// 知识库搜索只读取后端数据库，不再降级为前端示例数据。
export async function searchKnowledgeBases(search: string, team: string, signal: AbortSignal): Promise<{ items: KnowledgeBaseOption[]; demo: boolean }> {
  const token = useAuthStore.getState().session?.token
  if (!token) throw new Error('请先登录平台后再搜索知识库。')
  const response = await fetch(`/knowledge-bases/?search=${encodeURIComponent(search.trim())}`, { headers: { token }, signal })
  if (response.status === 401) { useAuthStore.getState().setSession(null); throw new Error('登录已失效') }
  if (!response.ok) throw new Error('知识库接口不可用')
  const result = await response.json()
  if (result.status !== 'success' || !Array.isArray(result.data)) throw new Error('知识库列表无效')
  void team
  return { demo: false, items: result.data.map((row: { id: string; knowledge_name: string; description?: string; is_public: boolean }) => ({ id: row.id, name: row.knowledge_name, description: row.description ?? '', scope: row.is_public ? '全平台' : '个人知识库', source: 'backend' as const })) }
}
