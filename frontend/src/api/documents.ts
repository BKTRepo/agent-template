import { apiClient } from './client'
import type { Document, DocChunksResponse, DocMarkdownResponse, DocStatusResponse, DocTerminologyResponse } from '@/types/api'

export async function listDocuments(): Promise<Document[]> {
  // 后端文档接口返回分页信封 { items, total }，前端状态只需要文档数组。
  const { data } = await apiClient.get<{ items?: Document[]; total?: number } | Document[]>('/documents')
  return Array.isArray(data) ? data : (data?.items ?? [])
}

/** 更新文档摘要（详情页编辑保存） */
export async function updateDocumentSummary(jobId: string, summary: string): Promise<{ job_id: string; summary: string }> {
  const { data } = await apiClient.post<{ job_id: string; summary: string }>(
    '/documents/summary',
    { job_id: jobId, summary },
  )
  return data
}

export async function getConvertStatus(
  jobId: string,
): Promise<DocStatusResponse> {
  const { data } = await apiClient.get<DocStatusResponse>(
    `/convert/status/${encodeURIComponent(jobId)}`,
  )
  return data
}

/** 获取文档解析产物的 markdown 全文（详情抽屉展示用） */
export async function getDocumentMarkdown(
  jobId: string,
): Promise<DocMarkdownResponse> {
  const { data } = await apiClient.get<DocMarkdownResponse>(
    `/documents/${encodeURIComponent(jobId)}/markdown`,
  )
  return data
}

/** 获取文档术语对照表 markdown（术语查看抽屉用） */
export async function getDocumentTerminology(
  jobId: string,
): Promise<DocTerminologyResponse> {
  const { data } = await apiClient.get<DocTerminologyResponse>(
    `/documents/${encodeURIComponent(jobId)}/terminology`,
  )
  return data
}

/** 获取文档最终入库的分块列表（分块查看抽屉用） */
export async function getDocumentChunks(
  jobId: string,
): Promise<DocChunksResponse> {
  const { data } = await apiClient.get<DocChunksResponse>(
    `/documents/${encodeURIComponent(jobId)}/chunks`,
  )
  return data
}
