import { apiClient } from './client'
import type { ConvertResponse, UpdateResponse } from '@/types/api'

export async function convertPdf(formData: FormData): Promise<ConvertResponse> {
  const { data } = await apiClient.post<ConvertResponse>('/convert', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
  return data
}

/** 重试失败的文档: 重置状态并重新分发 Celery 任务 */
export async function retryDocument(jobId: string): Promise<ConvertResponse> {
  const { data } = await apiClient.post<ConvertResponse>('/convert/retry', {
    job_id: jobId,
  })
  return data
}

/**
 * 增量更新既有文档: 保留同一 job_id, 用新文件重跑流水线。
 * 文件内容无变化时后端直接返回 unchanged=true, 不触发重新处理。
 * 与上传一致放宽超时: 大文件读取 + 服务端归档/哈希校验耗时。
 */
export async function updateDocumentFile(
  jobId: string,
  formData: FormData,
): Promise<UpdateResponse> {
  formData.append('job_id', jobId)
  const { data } = await apiClient.post<UpdateResponse>('/convert/update', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
  return data
}

/** 增量更新失败后回滚到上一版本: 先重写向量, 再恢复产物目录与文档字段 */
export async function rollbackDocument(jobId: string): Promise<ConvertResponse> {
  const { data } = await apiClient.post<ConvertResponse>('/convert/rollback', {
    job_id: jobId,
  })
  return data
}
