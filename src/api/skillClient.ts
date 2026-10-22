import { useAuthStore } from '@/stores/authStore'
import type { Implementation, SkillBuild, SkillUploads } from '@/types/developer'
import { hasSkillSession, skillAccount } from './skillSession'

interface Issue { field: string; reason: string }
interface ApiResponse<T> { status: string; message?: string; data: T }
export class SkillApiError extends Error {
  constructor(message: string, public fields: Record<string, string> = {}) { super(message) }
}
const fieldNames: Record<string, string> = { name: 'technicalName', display_name: 'name', skill_name: 'name', resource_usage: 'resourceUsage', skill_class_id: 'classId', model_tier: 'modelTier', application: 'applicationIds', resource_categories: 'uploadedResources' }
function fieldErrors(issues: Issue[] = []) {
  return Object.fromEntries(issues.map(issue => [issue.field.startsWith('knowledge_base_ids') ? 'resourceIds' : /^(files|reference_uploads|script_uploads|resources|resource_categories)/.test(issue.field) ? (issue.field.endsWith('.usage') ? 'resourceUsage' : 'uploadedResources') : fieldNames[issue.field] ?? issue.field, issue.reason]))
}
async function request<T>(path: string, options: RequestInit = {}, authenticated = true): Promise<T> {
  const token = useAuthStore.getState().session?.token
  if (authenticated && !hasSkillSession()) throw new SkillApiError('请先登录后再生成 Skill。')
  let response: Response
  try {
    response = await fetch(path, { ...options, headers: { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(authenticated && token ? { token } : {}), ...options.headers } })
  } catch { throw new SkillApiError('无法连接后端，请检查后端服务和代理配置。') }
  if (response.status === 401) { useAuthStore.getState().setSession(null); throw new SkillApiError('登录已失效，请重新登录。') }
  let result: ApiResponse<T>
  try { result = await response.json() } catch { throw new SkillApiError('后端未返回 JSON，请检查接口代理和后端启动状态。') }
  if (!response.ok || result.status !== 'success') {
    const data = result.data as { missing_fields?: Issue[]; errors?: Issue[] } | undefined
    const fields = fieldErrors([...(data?.missing_fields ?? []), ...(data?.errors ?? [])])
    throw new SkillApiError(Object.values(fields).join('；') || result.message || '请求失败，请检查填写内容。', fields)
  }
  return result.data
}
export async function login(username: string, password: string) {
  const data = await request<{ access_token: string; username: string; alias: string }>('/base/auth/access_token', { method: 'POST', body: JSON.stringify({ username, password }) }, false)
  useAuthStore.getState().setSession({ token: data.access_token, username: data.username, alias: data.alias })
}
export async function ensureSkill(item: Implementation) {
  const account = skillAccount()
  if (item.backendSkillId && item.backendAccount === account) return item.backendSkillId
  const data = await request<{ id: string }>('/skills/', { method: 'POST', body: JSON.stringify({ name: item.name, is_enabled: false }) })
  return data.id
}
export async function checkSkillName(name: string, excludeId?: string) {
  const params = new URLSearchParams({ name })
  if (excludeId) params.set('exclude_id', excludeId)
  return request<{ available: boolean }>(`/skills/name-availability?${params}`)
}
export async function buildSkill(item: Implementation, uploads: SkillUploads): Promise<SkillBuild> {
  if (item.resourceIds.some(id => !item.knowledgeBases?.some(row => row.id === id && row.source === 'backend'))) throw new SkillApiError('示例资源不能参与真实生成。', { resourceIds: '请选择真实知识库。' })
  if (!item.backendSkillId) throw new SkillApiError('尚未创建后端技能记录。')
  const all = [...uploads.references, ...uploads.scripts]
  const categoryNames: Record<string, string> = { '参考资料': 'reference', '模板': 'template', '静态资源': 'asset', '脚本': 'script' }
  const resourceCategories = all.map(upload => {
    const category = item.uploadedResources?.find(row => row.id === upload.id)?.category
    if (!category || !categoryNames[category]) throw new SkillApiError(`请选择 ${upload.file.name} 的资源用途分类。`, { uploadedResources: '每个上传资源都需要选择分类。' })
    return categoryNames[category]
  })
  const source = { skill_id: item.backendSkillId, skill_name: item.name, skill_class_id: item.classId, application: item.applicationIds?.[0] || null, description: item.description, version: item.version, expected_version: item.backendVersion, instructions: item.instructions, compatibility: item.compatibility ?? '', resource_usage: item.resourceUsage ?? '', knowledge_base_ids: item.resourceIds, resource_categories: resourceCategories }
  const form = new FormData()
  form.append('source', JSON.stringify(source))
  all.forEach(file => form.append('files', file.file))
  return request('/skills/form/builds', { method: 'POST', body: form })
}
export function readBuild(item: Implementation) {
  if (!item.backendSkillId || !item.buildId || item.buildOrigin !== 'backend') throw new SkillApiError('该记录是演示数据，没有真实 Skill 包。')
  return request<SkillBuild>(`/skills/${item.backendSkillId}/builds/${item.buildId}`)
}
export function readSkillDefinition(item: Implementation) {
  if (!item.backendSkillId || item.buildOrigin !== 'backend') throw new SkillApiError('该记录没有真实后端 Skill 定义。')
  return request<{ build: SkillBuild; markdown: string; version: string }>(`/skills/${item.backendSkillId}/definition`)
}
export function saveSkillDefinition(item: Implementation, markdown: string) {
  if (!item.backendSkillId) throw new SkillApiError('该技能没有后端记录。')
  return request<SkillBuild>(`/skills/${item.backendSkillId}/definition`, { method: 'PUT', body: JSON.stringify({ markdown, expected_version: item.backendVersion || item.version }) })
}
export async function downloadBuild(item: Implementation) {
  await readBuild(item)
  const token = useAuthStore.getState().session?.token
  const response = await fetch(`/skills/${item.backendSkillId}/builds/${item.buildId}/download`, { headers: token ? { token } : {} })
  if (!response.ok || !response.headers.get('Content-Type')?.includes('application/zip')) throw new SkillApiError('下载失败，请重新查询生成结果或登录。')
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a'); link.href = url; link.download = `${item.technicalName}.zip`; link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
