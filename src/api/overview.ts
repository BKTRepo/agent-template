import { authFetch } from './authFetch'
import { downloadBlob } from '@/lib/resourceStorage'

export type OverviewMetric = 'connected_users' | 'online_skills' | 'skill_calls' | 'knowledge_mounts'
  | 'active_users' | 'test_artifacts' | 'new_skills' | 'new_knowledge_bases'

export async function downloadOverviewMetric(metric: OverviewMetric, filename: string,
  period?: { start_date: string; end_date: string }, signal?: AbortSignal) {
  const params = new URLSearchParams({ metric, ...period })
  const response = await authFetch(`/overview/metric-export?${params}`, { cache: 'no-store', signal })
  if (!response.ok || response.headers.get('content-type')?.includes('application/json')) {
    const body = await response.json().catch(() => null)
    throw new Error(response.status === 401 ? '登录已失效，请重新登录。'
      : body?.message || (typeof body?.detail === 'string' && body.detail) || '明细下载失败，请重试。')
  }
  if (!response.headers.get('content-type')?.includes('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')) {
    throw new Error('接口未返回有效的 Excel 文件，请重试。')
  }
  downloadBlob(await response.blob(), filename)
}
