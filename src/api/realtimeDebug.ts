import { useAuthStore } from '@/stores/authStore'
import { useKnowledgeStore } from '@/stores/knowledgeStore'
import { readBlob, saveBlobs } from '@/lib/resourceStorage'
import type { DebugInput, Implementation } from '@/types/developer'

const base = '/realtime-test-case-gen'
export const realtimeDebugEnabled = import.meta.env?.VITE_REALTIME_DEBUG_ENABLED === 'true'
export const debugDocumentLimit = 10
export const mountedResourceLimit = 20
type DocumentUpload = { id: string; file: File }

function authHeaders(): HeadersInit {
  const token = useAuthStore.getState().session?.token
  // 本地联调 token 由同源代理注入，不打包进浏览器代码。
  return token ? { token } : {}
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  if (response.status === 401) return '调试接口鉴权失败，token 已过期或无效，请更新联调配置。'
  if (response.status === 403) return '当前账号没有运行调试或下载结果的权限。'
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('json')) return fallback
  const data = await response.json().catch(() => null)
  const detail = data?.detail
  if (Array.isArray(detail)) return detail.map(row => `${row.loc?.filter((part: string) => part !== 'body').join('.') || '参数'}：${row.msg || '不符合接口要求'}`).join('；')
  return typeof detail === 'string' ? detail : data?.message || fallback
}

function assertSuccess(data: Record<string, unknown>) {
  if (['failure', 'failed', 'error', 'timeout'].includes(String(data.status)) || data.success === false) {
    throw new Error(typeof data.message === 'string' ? data.message : '调试接口返回执行失败。')
  }
}

function documentName(disposition: string | null, fallback: string) {
  const encoded = disposition?.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1]
  const plain = disposition?.match(/filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)/i)
  let name = encoded || plain?.[1] || plain?.[2]?.trim() || fallback
  try { name = decodeURIComponent(name) } catch { /* 非 URL 编码的文件名保留原值。 */ }
  return name.replace(/[\\/<>:"|?*\x00-\x1f]/g, '_')
}

/** 仅提交可恢复的原文件；绝不把文件名称当成挂载文件发送。 */
export async function mountedDebugFiles(item: Implementation): Promise<File[]> {
  const files: File[] = []
  for (const resource of item.uploadedResources ?? []) {
    const blob = await readBlob(`resource:${resource.id}`)
    if (!blob) throw new Error(`挂载资源“${resource.name}”原文件缺失，请在技能中重新上传后再调试。`)
    files.push(new File([blob], resource.name, { type: blob.type, lastModified: resource.lastModified }))
  }
  for (const id of item.resourceIds) {
    const knowledge = useKnowledgeStore.getState().knowledgeBases.find(row => row.id === id)
    if (!knowledge) throw new Error('部分挂载资源缺少原文件，请先修改技能，移除历史示例文件或重新上传真实资源。')
    for (const resource of knowledge.files) {
      const blob = resource.sampleContent !== undefined ? new Blob([resource.sampleContent], { type: 'text/plain' }) : await readBlob(`resource:${resource.id}`)
      if (!blob) throw new Error(`知识库文件“${resource.name}”缺失，请重新上传后再调试。`)
      files.push(new File([blob], resource.name, { type: blob.type, lastModified: resource.lastModified }))
    }
  }
  if (item.buildOrigin === 'backend' && item.build?.files.some(row => row.path !== 'SKILL.md' && row.path !== 'manifest.json' && !files.some(file => row.path.split('/').pop() === file.name))) {
    throw new Error('部分后端包内资源只有文件信息，未取得原文件；请先重新上传对应资源再调试，避免遗漏挂载内容。')
  }
  if (files.length > mountedResourceLimit) throw new Error(`调试接口最多支持 ${mountedResourceLimit} 个挂载资源文件，当前有 ${files.length} 个，请调整挂载资源。`)
  return files
}

export async function downloadRealtimeDocument(runId: string, skillName: string, signal?: AbortSignal) {
  const response = await fetch(`${base}/runs/${encodeURIComponent(runId)}/document`, { headers: authHeaders(), signal, cache: 'no-store' })
  if (!response.ok) throw new Error(await errorMessage(response, '调试结果文档下载失败，请重试下载。'))
  const type = response.headers.get('content-type') ?? ''
  if (type.includes('json')) throw new Error(await errorMessage(response, '接口尚未返回结果文档，请稍后重试下载。'))
  if (type.includes('text/html')) throw new Error('下载接口返回了网页，请检查调试接口代理配置。')
  const blob = await response.blob()
  if (!blob.size) throw new Error('调试结果文档为空，请重新运行调试。')
  const signature = new Uint8Array(await blob.slice(0, 4).arrayBuffer())
  if (signature[0] !== 0x50 || signature[1] !== 0x4b) throw new Error('下载接口没有返回有效的 Excel 文件，请联系后端检查生成结果。')
  const name = documentName(response.headers.get('content-disposition'), `${skillName}-调试结果.xlsx`)
  const artifact = { key: `debug:realtime:${runId}`, name, format: 'Excel' as const }
  await saveBlobs([{ key: artifact.key, blob }])
  return artifact
}

export async function runRealtimeDebug(item: Implementation, input: DebugInput, markdown: string, documents: DocumentUpload[], signal?: AbortSignal): Promise<NonNullable<Implementation['debug']>> {
  if (!markdown.trim()) throw new Error('Skill 定义不能为空。')
  if (!input.conversation.trim() && !input.documents.length) throw new Error('请填写对话或上传需求文档，至少提供一项输入。')
  if (input.documents.length > debugDocumentLimit) throw new Error(`调试接口最多上传 ${debugDocumentLimit} 份需求文档。`)
  const form = new FormData()
  form.append('skill_definition', markdown)
  form.append('conversation_input', input.conversation.trim())
  for (const document of input.documents) {
    const upload = documents.find(row => row.id === document.id)
    if (!upload) throw new Error(`需求文档“${document.name}”原文件缺失，请重新选择。`)
    form.append('documents', upload.file, upload.file.name)
  }
  for (const file of await mountedDebugFiles(item)) form.append('mounted_resources', file, file.name)
  const response = await fetch(`${base}/generate`, { method: 'POST', headers: authHeaders(), body: form, signal })
  if (!response.ok) throw new Error(await errorMessage(response, '运行调试失败，请稍后重试。'))
  const type = response.headers.get('content-type') ?? ''
  if (!type.includes('json')) throw new Error('调试接口未返回 JSON，请检查接口代理配置。')
  const data = await response.json()
  assertSuccess(data)
  const result = data.data ?? data
  assertSuccess(result)
  const runId = result.run_id
  if (typeof runId !== 'string' || !runId.trim()) throw new Error('生成接口未返回有效的 run_id，无法下载结果文档。')
  // 下载失败也保留 run_id，用户可直接重试下载，无需重复生成。
  let artifact: NonNullable<Implementation['debug']>['artifact']
  let documentError: string | undefined
  try {
    const downloaded = await downloadRealtimeDocument(runId, item.name, signal)
    const count = result.document?.test_case_count
    artifact = typeof count === 'number' && Number.isFinite(count) ? { ...downloaded, count } : downloaded
  }
  catch (error) {
    if (signal?.aborted) throw error
    documentError = (error as Error).message
  }
  return { id: crypto.randomUUID(), buildId: item.buildId!, input, status: 'passed', output: '真实调试已完成，结果来自调试服务。', origin: 'backend', runId, artifact, documentError }
}
