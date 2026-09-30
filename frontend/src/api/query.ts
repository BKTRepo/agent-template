import { apiClient } from './client'
import type { QueryRequest, QueryResponseData } from '@/types/api'

/**
 * 非流式问答专用超时: 10 分钟。
 *
 * apiClient 全局 30s 超时适配会话列表/鉴权等快接口, 但 /query 是同步等待
 * 完整生成: 指代消解 → 术语改写 → 子查询分解 → 多路召回 → rerank → LLM 生成,
 * 慢回答耗时数分钟完全正常, 30s 一刀切必然在长回答时误报"请求失败"。
 *
 * 流式路径用原生 fetch 无超时且用户可手动停止; 非流式路径没有停止按钮,
 * 故保留一个宽裕但有限的兜底——真到 10 分钟说明后端已基本死亡, 此时报错
 * 解锁输入框才是正确行为（无限等待会把界面永久卡死在生成态）。
 * 取 600s 与后端 LLM 客户端（OpenAI SDK 默认）的单次调用超时对齐。
 */
const QUERY_TIMEOUT_MS = 600000

export async function sendQuery(
  request: QueryRequest,
): Promise<QueryResponseData> {
  const { data } = await apiClient.post<QueryResponseData>(
    '/query',
    request,
    { timeout: QUERY_TIMEOUT_MS },
  )
  return data
}

export function sendQueryStream(
  request: QueryRequest,
  signal: AbortSignal,
): Promise<Response> {
  return fetch('/api/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
}

/**
 * 重连会话中仍在途的流式生成（刷新/切换会话后用）。
 * 服务端无活动任务时以 no_active_stream 事件立即结束; 不会触发新的提问/生成。
 */
export function resumeQueryStream(
  conversationId: number,
  index: number,
  signal: AbortSignal,
): Promise<Response> {
  return fetch(
    `/api/query/stream/resume?conversation_id=${conversationId}&index=${index}`,
    { signal },
  )
}
