import { authFetch } from './authFetch'
import { request, toImplementation, type ServerSkill, type DeveloperCatalogOption } from './developerCenter'
import { useAuthStore } from '@/stores/authStore'
import { downloadBlob } from '@/lib/resourceStorage'
import type { Implementation, SkillBuild } from '@/types/developer'

export interface CatalogClass extends DeveloperCatalogOption { is_enabled: boolean; description: string }
export interface ClassDefinition extends CatalogClass { input_schema: Record<string, unknown> | null; output_schema: Record<string, unknown> | null; template: string | null }
export interface CatalogFilters { name: string; classId: string; system: string; maintainer: string }
export interface CatalogMetadata { skill_classes: CatalogClass[]; applications: DeveloperCatalogOption[]; maintainers: DeveloperCatalogOption[] }
interface CatalogRow extends ServerSkill { maintainer_id: string; maintainer_name: string; call_count: number | null; download_count: number | null }
const map = (row: CatalogRow): Implementation => ({ ...toImplementation({ ...row, resource_ids: row.resource_ids ?? [], instructions: row.instructions ?? '', technical_name: row.technical_name ?? '' }), catalog: true,
  maintainerId: row.maintainer_id, maintainerName: row.maintainer_name, callCount: row.call_count, downloadCount: row.download_count })
export async function getCatalogMetadata(signal?: AbortSignal): Promise<CatalogMetadata> {
  const result = await request<CatalogMetadata>('/skills/catalog/get-metadata', { signal })
  return { ...result, skill_classes: result.skill_classes.map(row => ({ ...row, id: String(row.id) })) }
}
export function getCatalogClass(classId: string, signal?: AbortSignal) {
  return request<ClassDefinition>(`/skills/catalog/get-class?${new URLSearchParams({ class_id: classId })}`, { signal })
}
export async function listCatalogSkills(filters: CatalogFilters, page = 1, signal?: AbortSignal) {
  const params = new URLSearchParams({ name: filters.name, application: filters.system, maintainer: filters.maintainer, page: String(page), page_size: '10' })
  if (filters.classId) params.set('class_id', filters.classId)
  const result = await request<{ items: CatalogRow[]; total: number; pages: number; page: number }>(`/skills/catalog/list-skills?${params}`, { signal })
  return { ...result, items: result.items.map(map) }
}
export async function getCatalogSkill(id: string, signal?: AbortSignal) {
  return map(await request<CatalogRow>(`/skills/catalog/get-skill?${new URLSearchParams({ skill_id: id })}`, { signal }))
}
export async function prepareCatalogTest(id: string, signal?: AbortSignal) {
  const item = await getCatalogSkill(id, signal)
  if (item.status !== '已上线') throw new Error('技能已下线，不能在线测试。')
  if (!item.buildId) throw new Error('发布构建缺失，请联系维护人。')
  const build = await request<SkillBuild>(`/skills/catalog/get-build?${new URLSearchParams({ skill_id: id, build_id: item.buildId })}`, { signal })
  if (build.build_id !== item.buildId || build.skill_version_id !== item.skillVersionId) throw new Error('发布版本已变更，请刷新后重试。')
  return { ...item, build }
}
async function binary(path: string, signal?: AbortSignal) {
  const token = useAuthStore.getState().session?.token
  const response = await authFetch(path, { headers: token ? { token } : {}, cache: 'no-store', signal })
  if (!response.ok) {
    const result = await response.json().catch(() => null)
    throw new Error(result?.message || '发布资源下载失败，请刷新技能目录后重试。')
  }
  return response
}
export async function downloadCatalogSkill(item: Implementation) {
  if (!item.buildId) throw new Error('发布构建缺失，请联系维护人。')
  const response = await binary(`/skills/catalog/download-skill?${new URLSearchParams({ skill_id: item.id, build_id: item.buildId })}`)
  if (!response.headers.get('content-type')?.includes('application/zip')) throw new Error('接口未返回有效的技能 ZIP。')
  downloadBlob(await response.blob(), `${item.technicalName || item.name}-${item.version}.zip`)
}
export async function catalogResourceFiles(item: Implementation): Promise<File[]> {
  if (!item.buildId || !item.build) throw new Error('尚未取得发布构建。')
  const files = []
  const entries = item.build.files.filter(row => row.path !== 'SKILL.md' && row.path !== 'manifest.json')
  if (entries.length > 20) throw new Error('调试接口最多支持 20 个挂载资源文件。')
  for (const entry of entries) {
    const response = await binary(`/skills/catalog/download-resource?${new URLSearchParams({ skill_id: item.id, build_id: item.buildId, path: entry.path })}`)
    files.push(new File([await response.blob()], entry.path.split('/').pop()!, { type: 'application/octet-stream' }))
  }
  return files
}
