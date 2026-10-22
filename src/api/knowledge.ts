import { useAuthStore } from '@/stores/authStore'
import { filterKnowledgeBases, useKnowledgeStore } from '@/stores/knowledgeStore'
import type { KnowledgeBaseOption } from '@/types/developer'
import { useAccessStore } from '@/stores/accessStore'

// 独立搜索入口，可供后续知识库管理页面复用；复用后端 search 参数及权限过滤。
export async function searchKnowledgeBases(search: string, team: string, signal: AbortSignal, localOnly = false): Promise<{ items: KnowledgeBaseOption[]; demo: boolean }> {
  const token = useAuthStore.getState().session?.token
  if (token && !localOnly) {
    try {
      const response = await fetch(`/knowledge-bases/?search=${encodeURIComponent(search.trim())}`, { headers: { token }, signal })
      if (response.status === 401) { useAuthStore.getState().setSession(null); throw new Error('登录已失效') }
      if (!response.ok) throw new Error('知识库接口不可用')
      const result = await response.json()
      if (result.status !== 'success' || !Array.isArray(result.data)) throw new Error('知识库列表无效')
      return { demo: false, items: result.data.map((row: { id: string; knowledge_name: string; description?: string; is_public: boolean }) => ({ id: row.id, name: row.knowledge_name, description: row.description ?? '', scope: row.is_public ? '全平台' : '个人知识库', source: 'backend' as const })) }
    } catch (error) { if (signal.aborted) throw error }
  }
  void team
  return { demo: true, items: filterKnowledgeBases(useKnowledgeStore.getState().knowledgeBases, search, useAccessStore.getState().actor).map(row => ({ id: row.id, name: row.name, description: row.description, scope: row.scope === 'public' ? '全平台' : '仅本人可见', source: 'mock' as const })) }
}
