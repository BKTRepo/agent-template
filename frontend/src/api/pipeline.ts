import { apiClient } from './client'
import type { PipelineStatus, PipelineCancelResponse } from '@/types/api'

export async function getPipelineStatus(): Promise<PipelineStatus> {
  const { data } = await apiClient.get<PipelineStatus>('/pipeline/status')
  return data
}

/**
 * 取消所有进行中的任务。
 * @param force true = 杀掉运行中的 Worker 子进程使取消立即生效
 *              （默认软取消需等当前子文档解析结束）
 */
export async function cancelPipeline(force = false): Promise<PipelineCancelResponse> {
  const { data } = await apiClient.post<PipelineCancelResponse>(
    '/pipeline/cancel',
    null,
    force ? { params: { force: true } } : undefined,
  )
  return data
}
