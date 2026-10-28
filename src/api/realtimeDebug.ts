import { useAuthStore } from '@/stores/authStore'
import { useKnowledgeStore } from '@/stores/knowledgeStore'
import { readBlob, saveBlobs } from '@/lib/resourceStorage'
import { debugDocumentLimits, documentExtensions, validateResourceFiles } from '@/lib/skillForm'
import { DeveloperCenterError, getDeveloperDebugLink, recordDeveloperDebugResult } from './developerCenter'
import type { DebugInput, Implementation, RealtimeTask } from '@/types/developer'

const base = '/realtime-test-case-gen'
export const realtimeDebugEnabled = import.meta.env?.VITE_REALTIME_DEBUG_ENABLED === 'true'
export const debugDocumentLimit = 10
export const mountedResourceLimit = 20
export const debugPollInterval = 5000
type DocumentUpload = { id: string; file: File }
type DebugRun = NonNullable<Implementation['debug']>
export interface DebugMonitorOptions {
  onProgress?: (result: DebugRun) => void | Promise<void>
  pollIntervalMs?: number
}
interface PendingReceipt {
  runId: string; skillId: string; buildId: string; skillVersionId?: number
  conversation: string; documentCount: number
}
const creating = new Map<string, Promise<{ task: RealtimeTask; debug: DebugRun }>>()

// 只暂存尚未登记成功的任务收据；成功后删除，业务列表及版本仍从后端读取。
function receiptKey(item: Implementation) {
  return `znfwdd-pending-debug:${item.creatorId ?? 'platform'}:${item.backendSkillId || item.id}`
}
function receipt(item: Implementation): PendingReceipt | undefined {
  try {
    const value = JSON.parse(localStorage.getItem(receiptKey(item)) || 'null')
    if (value?.skillId === (item.backendSkillId || item.id) && typeof value.runId === 'string' && value.runId && typeof value.buildId === 'string' && value.buildId) return value
  } catch { /* 存储不可用时仍尝试后端登记，不将浏览器缓存当成业务数据源。 */ }
}
function saveReceipt(item: Implementation, debug: DebugRun) {
  try {
    localStorage.setItem(receiptKey(item), JSON.stringify({ runId: debug.runId!, skillId: item.backendSkillId || item.id,
      buildId: debug.buildId, skillVersionId: debug.skillVersionId,
      conversation: debug.conversationInput ?? '', documentCount: debug.requestDocumentCount ?? 0 } satisfies PendingReceipt))
  } catch { /* 后端登记成功后不需要该收据。 */ }
}
function removeReceipt(item: Implementation, runId: string) {
  try { if (receipt(item)?.runId === runId) localStorage.removeItem(receiptKey(item)) } catch { /* 无需更改任务。 */ }
}
function aborted(signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException('已停止前端查询', 'AbortError')
}
function pause(milliseconds: number, signal?: AbortSignal) {
  aborted(signal)
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => { signal?.removeEventListener('abort', cancel); resolve() }, milliseconds)
    function cancel() { clearTimeout(timer); signal?.removeEventListener('abort', cancel); reject(new DOMException('已停止前端查询', 'AbortError')) }
    signal?.addEventListener('abort', cancel, { once: true })
  })
}

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
    let blob = await readBlob(`resource:${resource.id}`)
    if (!blob && resource.downloadUrl?.startsWith('/skills/developer/resources/')) {
      const response = await fetch(resource.downloadUrl, { headers: authHeaders(), cache: 'no-store' })
      if (!response.ok) throw new Error(await errorMessage(response, `挂载资源“${resource.name}”下载失败。`))
      if (/json|text\/html/.test(response.headers.get('content-type') || '')) throw new Error(`挂载资源“${resource.name}”没有返回原文件。`)
      blob = await response.blob()
    }
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

async function taskResponse(response: Response, skillId: string): Promise<RealtimeTask> {
  if (!response.ok) throw new Error(await errorMessage(response, '调试任务请求失败，请重试查询。'))
  if (!(response.headers.get('content-type') || '').includes('json')) throw new Error('调试接口未返回 JSON，请检查接口代理配置。')
  const payload = await response.json()
  if (payload?.status === 'failure' || payload?.success === false) throw new Error(payload.message || '调试接口请求失败。')
  const value = payload?.data ?? payload
  if (typeof value?.run_id !== 'string' || !value.run_id.trim()) throw new Error('调试接口未返回有效的 run_id。')
  if (value.skill_id !== skillId) throw new Error('调试接口返回的任务不属于当前技能，已停止处理。')
  if (!['queued', 'running', 'completed', 'failed'].includes(value.status)) throw new Error('调试接口返回了无法识别的任务状态。')
  return { run_id: value.run_id, skill_id: value.skill_id, status: value.status,
    started_at: value.started_at ?? null, finished_at: value.finished_at ?? null, error_message: value.error_message ?? null }
}

export async function getRealtimeRun(skillId: string, runId: string, signal?: AbortSignal) {
  const response = await fetch(`${base}/runs/${encodeURIComponent(runId)}`, { headers: authHeaders(), signal, cache: 'no-store' })
  const task = await taskResponse(response, skillId)
  if (task.run_id !== runId) throw new Error('调试接口返回了其他任务编号，已停止处理。')
  return task
}
export async function getLatestRealtimeRun(skillId: string, signal?: AbortSignal) {
  const response = await fetch(`${base}/skills/${encodeURIComponent(skillId)}/latest-run`, { headers: authHeaders(), signal, cache: 'no-store' })
  if (response.status === 404) return null
  return taskResponse(response, skillId)
}

function withTask(debug: DebugRun, task: RealtimeTask): DebugRun {
  return { ...debug, id: task.run_id, runId: task.run_id, status: task.status === 'completed' ? 'passed' : task.status,
    output: task.status === 'failed' ? task.error_message || '沙箱执行失败，请检查输入后重试。'
      : task.status === 'queued' ? '任务已创建，等待执行。' : task.status === 'running' ? '沙箱正在运行。' : '调试已完成，可下载结果文档。' }
}

async function verifyLink(item: Implementation, debug: DebugRun): Promise<DebugRun> {
  const link = await getDeveloperDebugLink(item.backendSkillId || item.id, debug.runId!)
  if (link.run_id !== debug.runId || link.skill_id !== (item.backendSkillId || item.id)
    || (debug.buildId && link.build_id !== debug.buildId)
    || (debug.skillVersionId && link.skill_version_id !== debug.skillVersionId)) throw new Error('任务的技能版本关联不一致，已停止处理。')
  removeReceipt(item, debug.runId!)
  return { ...debug, buildId: link.build_id, skillVersionId: link.skill_version_id,
    versionRegistered: true, isCurrentVersion: link.is_current_version, registrationError: undefined }
}

async function monitor(item: Implementation, first: RealtimeTask, initial: DebugRun, signal?: AbortSignal, options: DebugMonitorOptions = {}): Promise<DebugRun> {
  let task = first, debug = initial
  for (;;) {
    debug = withTask({ ...debug, monitorError: undefined }, task)
    if (!debug.versionRegistered && debug.buildId) {
      try {
        // 任务创建后的登记不随窗口关闭而取消；仅后续状态查询接受AbortSignal。
        await recordDeveloperDebugResult(item.backendSkillId || item.id, debug)
        debug = await verifyLink(item, debug)
      } catch (error) {
        debug = { ...debug, registrationError: `任务已创建，版本关联尚未保存：${(error as Error).message}。请重试关联，不要重复创建任务。` }
      }
    }
    aborted(signal)
    if (task.status === 'completed' || task.status === 'failed') {
      if (debug.versionRegistered) {
        try { debug = await verifyLink(item, debug) }
        catch (error) { debug = { ...debug, monitorError: `暂时无法核对任务版本：${(error as Error).message}` } }
      }
      if (task.status === 'completed' && !debug.artifact) {
        try { debug = { ...debug, artifact: await downloadRealtimeDocument(task.run_id, item.name, signal), documentError: undefined } }
        catch (error) { aborted(signal); debug = { ...debug, documentError: (error as Error).message } }
      }
      aborted(signal)
      await options.onProgress?.(debug)
      return debug
    }
    await options.onProgress?.(debug)
    try {
      await pause(Math.max(1, options.pollIntervalMs ?? debugPollInterval), signal)
      task = await getRealtimeRun(task.skill_id, task.run_id, signal)
    } catch (error) {
      aborted(signal)
      debug = { ...debug, monitorError: `状态查询中断：${(error as Error).message}。后台任务会继续运行，可以继续查询。` }
      await options.onProgress?.(debug)
      return debug
    }
  }
}

export async function restoreRealtimeDebug(item: Implementation, signal?: AbortSignal, options: DebugMonitorOptions = {}): Promise<DebugRun | undefined> {
  const skillId = item.backendSkillId || item.id
  const pending = receipt(item)
  let task = await getLatestRealtimeRun(skillId, signal)
  if (pending && (!task || pending.runId !== task.run_id)) task = await getRealtimeRun(skillId, pending.runId, signal)
  if (!task) return undefined
  let debug: DebugRun = { id: task.run_id, runId: task.run_id, buildId: '', input: '', status: 'idle', output: '', origin: 'backend', isCurrentVersion: false }
  try { debug = await verifyLink(item, debug) }
  catch (error) {
    if (!(error instanceof DeveloperCenterError) || error.statusCode !== 404) throw error
    if (pending?.runId === task.run_id) {
      debug = { ...debug, buildId: pending.buildId, skillVersionId: pending.skillVersionId,
        conversationInput: pending.conversation, requestDocumentCount: pending.documentCount }
    } else {
      // latest-run没有版本信息；没有原始收据时绝不能拿当前版本替历史任务补登记。
      debug.registrationError = '该任务尚未关联技能版本，不能作为当前版本调试通过的依据。请重新调试当前版本。'
    }
  }
  aborted(signal)
  return monitor(item, task, debug, signal, options)
}

export async function resumeRealtimeDebug(item: Implementation, debug: DebugRun, signal?: AbortSignal, options: DebugMonitorOptions = {}) {
  if (!debug.runId) return restoreRealtimeDebug(item, signal, options)
  const task = await getRealtimeRun(item.backendSkillId || item.id, debug.runId, signal)
  return monitor(item, task, debug, signal, options)
}

async function createDebugTask(item: Implementation, input: DebugInput, markdown: string, documents: DocumentUpload[]) {
  if (!markdown.trim()) throw new Error('Skill 定义不能为空。')
  if (!item.buildId) throw new Error('缺少本次实际构建编号，请先生成当前版本。')
  if (!input.conversation.trim() && !input.documents.length) throw new Error('请填写对话或上传需求文档，至少提供一项输入。')
  if (input.documents.length > debugDocumentLimit) throw new Error(`调试接口最多上传 ${debugDocumentLimit} 份需求文档。`)
  const form = new FormData()
  form.append('skill_definition', markdown)
  form.append('skill_id', item.backendSkillId || item.id)
  form.append('conversation_input', input.conversation.trim())
  const selected: File[] = []
  for (const document of input.documents) {
    const upload = documents.find(row => row.id === document.id)
    if (!upload) throw new Error(`需求文档“${document.name}”原文件缺失，请重新选择。`)
    selected.push(upload.file)
    form.append('documents', upload.file, upload.file.name)
  }
  const checked = validateResourceFiles(selected, [], documentExtensions, debugDocumentLimits)
  if (checked.errors.length) throw new Error(checked.errors.join('；'))
  for (const file of await mountedDebugFiles(item)) form.append('mounted_resources', file, file.name)
  const response = await fetch(`${base}/runs`, { method: 'POST', headers: authHeaders(), body: form })
  const task = await taskResponse(response, item.backendSkillId || item.id)
  const debug: DebugRun = { id: task.run_id, runId: task.run_id, buildId: item.buildId,
    skillVersionId: item.skillVersionId, input, conversationInput: input.conversation.trim(), requestDocumentCount: input.documents.length,
    status: 'queued', output: '', origin: 'backend', versionRegistered: false }
  saveReceipt(item, debug)
  return { task, debug }
}

export async function runRealtimeDebug(item: Implementation, input: DebugInput, markdown: string, documents: DocumentUpload[], signal?: AbortSignal, options: DebugMonitorOptions = {}): Promise<DebugRun> {
  aborted(signal)
  if (receipt(item)) {
    const recovered = await restoreRealtimeDebug(item, signal, options)
    if (recovered) return recovered
  }
  const key = `${receiptKey(item)}:${item.buildId}`
  let pending = creating.get(key)
  if (!pending) {
    pending = createDebugTask(item, input, markdown, documents)
    creating.set(key, pending)
  }
  let created: Awaited<NonNullable<typeof pending>>
  try { created = await pending }
  finally { if (creating.get(key) === pending) creating.delete(key) }
  return monitor(item, created.task, created.debug, signal, options)
}
