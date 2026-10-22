import { useAuthStore } from '@/stores/authStore'
import type { Implementation, ImplementationForm } from '@/types/developer'

interface ApiResponse<T> { status: string; message?: string; data: T }
interface ServerSkill {
  id: string; name: string; class_id: string; application_ids: string[]; description: string
  instructions: string; resource_ids: string[]; resource_usage: string; compatibility: string
  technical_name: string; uploaded_resources: Implementation['uploadedResources']; knowledge_bases: Implementation['knowledgeBases']
  skill_markdown?: string; version: string; status: Implementation['status']; creator_id: string; creator_name: string; updated_at: string
  backend_skill_id?: string; build_id?: string; build_origin?: 'backend'
  debug?: { id: string; runId: string; buildId?: string; status: 'passed' | 'failed' | 'timeout'; output: string; origin: 'backend' }
}
export interface DeveloperCatalogOption { id: string; name: string }
export interface DeveloperMetadata { skill_classes: DeveloperCatalogOption[]; applications: DeveloperCatalogOption[] }

export class DeveloperCenterError extends Error {}

function toImplementation(row: ServerSkill): Implementation {
  return {
    id: row.id, name: row.name, classId: row.class_id, applicationIds: row.application_ids,
    system: row.application_ids.includes('*') ? '全应用适用' : row.application_ids[0] || '', team: '',
    technicalName: row.technical_name, description: row.description, instructions: row.instructions,
    resourceIds: row.resource_ids, resourceUsage: row.resource_usage, compatibility: row.compatibility,
    uploadedResources: row.uploaded_resources ?? [], knowledgeBases: row.knowledge_bases ?? [], skillMarkdown: row.skill_markdown,
    version: row.version, modelTier: 'standard', status: row.status, creatorId: row.creator_id,
    creatorName: row.creator_name, updatedAt: row.updated_at,
    backendSkillId: row.backend_skill_id ?? row.id, buildId: row.build_id,
    buildOrigin: row.build_origin, debug: row.debug ? { ...row.debug, buildId: row.debug.buildId ?? row.build_id ?? '', input: '' } : undefined,
  }
}

function body(form: ImplementationForm) {
  return { name: form.name, class_id: form.classId, application_ids: form.applicationIds ?? [], description: form.description,
    instructions: form.instructions, resource_ids: form.resourceIds, resource_usage: form.resourceUsage ?? '',
    compatibility: form.compatibility ?? '', technical_name: form.technicalName, uploaded_resources: form.uploadedResources ?? [],
    knowledge_bases: form.knowledgeBases ?? [], skill_markdown: form.skillMarkdown }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = useAuthStore.getState().session?.token
  if (!token) throw new DeveloperCenterError('请先登录平台后再使用开发者中心。')
  let response: Response
  try { response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', token, ...options.headers } }) }
  catch { throw new DeveloperCenterError('无法连接后端，请检查后端服务是否已启动。') }
  let result: ApiResponse<T>
  try { result = await response.json() } catch { throw new DeveloperCenterError('后端返回格式异常。') }
  if (!response.ok || result.status !== 'success') throw new DeveloperCenterError(result.message || '操作失败，请稍后重试。')
  return result.data
}

export async function listDeveloperSkills() { return (await request<ServerSkill[]>('/skills/developer/')).map(toImplementation) }
export async function getDeveloperMetadata() { return request<DeveloperMetadata>('/skills/developer/metadata') }
export async function createDeveloperSkill(form: ImplementationForm) { return toImplementation(await request<ServerSkill>('/skills/developer/', { method: 'POST', body: JSON.stringify(body(form)) })) }
export async function updateDeveloperSkill(id: string, form: ImplementationForm) { return toImplementation(await request<ServerSkill>(`/skills/developer/${id}`, { method: 'PUT', body: JSON.stringify(body(form)) })) }
export async function deleteDeveloperSkill(id: string) { await request<unknown>(`/skills/developer/${id}`, { method: 'DELETE' }) }
export async function offlineDeveloperSkill(id: string) { return toImplementation(await request<ServerSkill>(`/skills/developer/${id}/offline`, { method: 'POST' })) }
export async function publishDeveloperSkill(id: string) { return toImplementation(await request<ServerSkill>(`/skills/developer/${id}/publish`, { method: 'POST' })) }
export async function recordDeveloperDebugResult(id: string, debug: NonNullable<Implementation['debug']>) {
  if (!debug.runId || !['passed', 'failed', 'timeout'].includes(debug.status)) return
  const conversation = typeof debug.input === 'string' ? debug.input : debug.input.conversation
  const documents = typeof debug.input === 'string' ? [] : debug.input.documents
  return toImplementation(await request<ServerSkill>(`/skills/developer/${id}/debug-result`, {
    method: 'POST', body: JSON.stringify({ run_id: debug.runId, build_id: debug.buildId || null,
      status: debug.status, conversation_input: conversation, request_document_count: documents.length,
      result_file_name: debug.artifact?.name ?? null, error_message: debug.status === 'passed' ? null : debug.output })
  }))
}
