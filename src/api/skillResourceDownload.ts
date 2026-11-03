import type { UploadedResource } from '@/types/developer'

/** 将旧页面缓存中的资源地址转换为 GET 查询参数接口，不请求已移除的旧路由。 */
export function skillResourceDownloadUrl(resource: UploadedResource): string | undefined {
  const stored = resource.downloadUrl
  const oldId = stored?.match(/^\/skills\/developer\/resources\/(\d+)\/download$/)?.[1]
  const queryId = stored?.startsWith('/skills/developer/download-resource-file?')
    ? new URLSearchParams(stored.split('?')[1]).get('file_id') : undefined
  const id = resource.fileId ?? resource.sourceId ?? oldId ?? queryId
  if (id !== undefined && id !== null && /^\d+$/.test(String(id)) && Number(id) > 0) {
    return `/skills/developer/download-resource-file?${new URLSearchParams({ file_id: String(id) })}`
  }
  return undefined
}
