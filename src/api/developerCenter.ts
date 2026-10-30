import { useAuthStore } from '@/stores/authStore'
import { hasSkillSession } from './skillSession'
import { restoreSkillUploads } from './skillArchive'
import type { Implementation, ImplementationForm, SkillUploads } from '@/types/developer'

interface ApiResponse<T> { status: string; message?: string; data: T }
interface ServerSkill {
  id: string; name: string; class_id: string | number; application_ids?: string[]; application_paso?: string; description: string
  instructions: string; resource_ids: string[]; resource_usage: string; compatibility: string
  technical_name: string; uploaded_resources: Implementation['uploadedResources']; knowledge_bases: Implementation['knowledgeBases']
  current_revision: number; skill_version_id: number; skill_markdown?: string; version: string | null; status: Implementation['status']; creator_id?: string; creator_login_name?: string; creator_name: string; updated_at: string
  backend_skill_id?: string; build_id?: string; build_origin?: 'backend'
  debug?: { id: string; runId: string; buildId?: string; skillVersionId?: number; status: 'queued' | 'running' | 'passed' | 'failed' | 'timeout'; output: string; origin: 'backend' }
}
export interface DeveloperCatalogOption { id: string; name: string }
export interface DeveloperMetadata { skill_classes: DeveloperCatalogOption[]; applications: DeveloperCatalogOption[] }

export class DeveloperCenterError extends Error {
  constructor(message: string, public statusCode?: number) { super(message) }
}
export interface DeveloperSkillPage {
  items: Implementation[]
  total: number
  page: number
  pageSize: number
  pages: number
}
export interface DeveloperDebugLink {
  run_id: string; skill_id: string; skill_version_id: number; version: string
  build_id: string; is_current_version: boolean; task: Record<string, unknown> | null
}

function toImplementation(row: ServerSkill): Implementation {
  const applicationIds = row.application_ids ?? (row.application_paso ? [row.application_paso] : [])
  return {
    id: row.id, revision: row.current_revision, skillVersionId: row.skill_version_id, backendVersion: row.version ?? undefined, name: row.name, classId: String(row.class_id), applicationIds,
    system: applicationIds.includes('*') ? '全应用适用' : applicationIds[0] || '', team: '',
    technicalName: row.technical_name, description: row.description, instructions: row.instructions,
    resourceIds: row.resource_ids, resourceUsage: row.resource_usage, compatibility: row.compatibility,
    uploadedResources: row.uploaded_resources ?? [], knowledgeBases: row.knowledge_bases ?? [], skillMarkdown: row.skill_markdown,
    version: row.version ?? '', modelTier: 'standard', status: row.status, creatorId: row.creator_id,
    creatorName: row.creator_name, updatedAt: row.updated_at,
    backendSkillId: row.backend_skill_id ?? row.id, buildId: row.build_id,
    buildOrigin: row.build_origin, debug: row.debug ? { ...row.debug, buildId: row.debug.buildId ?? '', input: '',
      versionRegistered: !!row.debug.buildId, isCurrentVersion: !!row.debug.buildId && row.debug.buildId === row.build_id,
    } : undefined,
  }
}

function body(form: ImplementationForm) {
  return { expected_revision: form.revision, name: form.name, class_id: Number(form.classId), application_ids: form.applicationIds ?? [], description: form.description,
    instructions: form.instructions, resource_ids: form.resourceIds, resource_usage: form.resourceUsage ?? '',
    compatibility: form.compatibility ?? '', technical_name: form.technicalName, uploaded_resources: (form.uploadedResources ?? []).map(row => ({ ...row, fileId: row.fileId ?? row.sourceId })),
    knowledge_bases: form.knowledgeBases ?? [], skill_markdown: form.skillMarkdown }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = useAuthStore.getState().session?.token
  if (!hasSkillSession()) throw new DeveloperCenterError('平台认证未配置，请检查接口代理的token配置。')
  let response: Response
  try { response = await fetch(path, { ...options, cache: options.cache ?? 'no-store', headers: { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(token ? { token } : {}), ...options.headers } }) }
  catch (error) { if (options.signal?.aborted) throw error; throw new DeveloperCenterError('无法连接后端，请检查后端服务是否已启动。') }
  if (response.status === 401) {
    useAuthStore.getState().setSession(null)
    throw new DeveloperCenterError('平台凭证已失效，请更新服务端代理token。')
  }
  let result: ApiResponse<T>
  try { result = await response.json() } catch { throw new DeveloperCenterError('后端返回格式异常。') }
  if (!response.ok || result.status !== 'success') throw new DeveloperCenterError(result.message || '操作失败，请稍后重试。', response.status)
  return result.data
}

export async function listDeveloperSkillsPage(page = 1, pageSize = 10): Promise<DeveloperSkillPage> {
  const params = new URLSearchParams({ page: String(Math.max(1, page)), page_size: String(Math.max(1, pageSize)) })
  const result = await request<ServerSkill[] | { items: ServerSkill[]; total: number; page: number; page_size: number; pages: number }>(`/skills/developer?${params.toString()}`)
  if (Array.isArray(result)) {
    const items = result.map(toImplementation)
    return { items, total: items.length, page: 1, pageSize: items.length || pageSize, pages: 1 }
  }
  return { items: result.items.map(toImplementation), total: result.total, page: result.page, pageSize: result.page_size, pages: result.pages }
}
// 保留数组返回形态，兼容旧的调试脚本与调用方；需要分页信息时使用 listDeveloperSkillsPage。
export async function listDeveloperSkills(page = 1, pageSize = 10) {
  return (await listDeveloperSkillsPage(page, pageSize)).items
}
export async function getDeveloperMetadata() {
  const metadata = await request<DeveloperMetadata>('/skills/developer/metadata')
  return { ...metadata, skill_classes: metadata.skill_classes.map(row => ({ ...row, id: String(row.id) })) }
}
export async function createDeveloperSkill(form: ImplementationForm) { return toImplementation(await request<ServerSkill>('/skills/developer/', { method: 'POST', body: JSON.stringify(body(form)) })) }
export async function updateDeveloperSkill(id: string, form: ImplementationForm) { return toImplementation(await request<ServerSkill>(`/skills/developer/${id}`, { method: 'PUT', body: JSON.stringify(body(form)) })) }
export async function deleteDeveloperSkill(id: string) { await request<unknown>(`/skills/developer/${id}`, { method: 'DELETE' }) }
export async function offlineDeveloperSkill(id: string, reasonCode = 'ABILITY_DEFECT', reasonText?: string) {
  return toImplementation(await request<ServerSkill>(`/skills/developer/${id}/offline`, { method: 'POST', body: JSON.stringify({ reason_code: reasonCode, reason_text: reasonText || null }) }))
}
export async function publishDeveloperSkill(id: string) { return toImplementation(await request<ServerSkill>(`/skills/developer/${id}/publish`, { method: 'POST' })) }
export async function recordDeveloperDebugResult(id: string, debug: NonNullable<Implementation['debug']>) {
  if (!debug.runId || debug.status === 'idle') return
  if (!debug.buildId && !debug.skillVersionId) throw new DeveloperCenterError('缺少本次任务实际使用的技能版本，不能登记。')
  const conversation = typeof debug.input === 'string' ? debug.input : debug.input.conversation
  const documents = typeof debug.input === 'string' ? [] : debug.input.documents
  return toImplementation(await request<ServerSkill>(`/skills/developer/${encodeURIComponent(id)}/debug-runs`, {
    method: 'POST', body: JSON.stringify({ run_id: debug.runId, build_id: debug.buildId || null,
      skill_version_id: debug.skillVersionId, conversation_input: debug.conversationInput ?? conversation,
      request_document_count: debug.requestDocumentCount ?? documents.length })
  }))
}
export function getDeveloperDebugLink(id: string, runId: string, signal?: AbortSignal) {
  return request<DeveloperDebugLink>(`/skills/developer/${encodeURIComponent(id)}/debug-runs/${encodeURIComponent(runId)}`, { signal })
}

export function getPlatformContext() { return request<{ id: string; name: string }>('/skills/developer/context') }
export async function persistSkillResources(form: ImplementationForm, uploads: SkillUploads): Promise<ImplementationForm> {
  const rows = form.uploadedResources ?? []
  if (!rows.some(row => !row.fileId || row.savedCategory !== row.category)) return form
  const restored = await restoreSkillUploads(form, uploads)
  const files = [...restored.references, ...restored.scripts]
  const saved = []
  for (const row of rows) {
    if (row.fileId && row.savedCategory === row.category) { saved.push(row); continue }
    const file = files.find(upload => upload.id === row.id)?.file
    if (!file || !row.category) throw new DeveloperCenterError('请补充资源文件及用途分类。')
    const data = new FormData(); data.append('files', file, row.name); data.append('categories', JSON.stringify([row.category]))
    const path = '/skills/developer/resources'
    const result = await request<NonNullable<ImplementationForm['uploadedResources']>>(path, { method: 'POST', body: data })
    saved.push({ ...result[0], savedCategory: result[0].category, fileId: result[0].fileId })
  }
  return { ...form, uploadedResources: saved }
}
