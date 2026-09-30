import { apiClient } from './client'
import type { DeleteFilesResponse } from '@/types/api'

/** 删除文档及其全部产物: 源文件留档、解析产物目录、向量库分块均由服务端按 job_id 推导清理 */
export async function deleteFiles(jobIds: string[]): Promise<DeleteFilesResponse> {
  const fd = new FormData()
  fd.append('job_ids', jobIds.join('\n'))
  const { data } = await apiClient.post<DeleteFilesResponse>(
    '/files/delete',
    fd,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}
