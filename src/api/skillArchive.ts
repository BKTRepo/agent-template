import { createZip } from '@/lib/zip'
import type { ZipEntry } from '@/lib/zip'
import { downloadBlob, readBlob, saveBlobs } from '@/lib/resourceStorage'
import { withSystemVersion } from '@/lib/skillModel'
import { useKnowledgeStore } from '@/stores/knowledgeStore'
import { downloadBuild } from './skillClient'
import type { Implementation, ImplementationForm, SkillUploads } from '@/types/developer'

const encoder = new TextEncoder()
const safeName = (name: string) => name.replace(/[\\/<>:"|?*\x00-\x1f]/g, '_')
export function renderSkillMarkdown(item: ImplementationForm, paths: string[] = []) {
  if (item.skillMarkdown) return withSystemVersion(item.skillMarkdown, item.version)
  if (!paths.length) paths = [...(item.knowledgeBases?.map(row => row.name) ?? []), ...(item.uploadedResources?.map(row => row.name) ?? [])]
  return `---\nname: ${JSON.stringify(item.technicalName)}\ndisplay_name: ${JSON.stringify(item.name)}\ndescription: ${JSON.stringify(item.description)}\nversion: ${JSON.stringify(item.version)}\ncompatibility: ${JSON.stringify(item.compatibility ?? '')}\n---\n\n# ${item.name}\n\n${item.instructions}\n\n## 资源使用说明\n${item.resourceUsage || '无挂载资源'}\n\n## 挂载资源\n${paths.map(path => `- ${path}`).join('\n') || item.knowledgeBases?.map(row => `- ${row.name}`).join('\n') || '无'}\n\n> 前端示例定义，未调用模型或执行脚本。\n`
}
export async function restoreSkillUploads(item: ImplementationForm, provided: SkillUploads = { references: [], scripts: [] }): Promise<SkillUploads> {
  const next: SkillUploads = { references: [], scripts: [] }
  const all = [...provided.references, ...provided.scripts]
  for (const row of item.uploadedResources ?? []) {
    const selected = all.find(upload => upload.id === row.id)
    const blob = selected?.file ?? await readBlob(`resource:${row.id}`)
    if (!blob) throw new Error(`资源 ${row.name} 原文件缺失，请重新选择或移除后再保存。`)
    const file = selected?.file ?? new File([blob], row.name, { lastModified: row.lastModified, type: blob.type })
    next[row.category === '脚本' ? 'scripts' : 'references'].push({ id: row.id, file, usage: row.category ?? '' })
  }
  return next
}
export async function buildMockArchive(item: Implementation, uploads: SkillUploads) {
  const entries: ZipEntry[] = []
  const selected = item.resourceIds.map(id => {
    const kb = useKnowledgeStore.getState().knowledgeBases.find(row => row.id === id)
    if (!kb) throw new Error('部分挂载资源缺少原文件，请重新选择知识库或上传原文件。')
    return kb
  })
  for (const kb of selected) for (const file of kb.files) {
    const blob = file.sampleContent !== undefined ? new Blob([file.sampleContent]) : await readBlob(`resource:${file.id}`)
    if (!blob) throw new Error(`知识库文件 ${file.name} 缺失，请在知识库管理中重新上传。`)
    entries.push({ path: `references/${safeName(kb.id)}/${safeName(file.name)}`, data: new Uint8Array(await blob.arrayBuffer()) })
  }
  const all = [...uploads.references, ...uploads.scripts]
  if (item.uploadedResources?.some(row => !all.some(upload => upload.id === row.id))) throw new Error('上传资源原文件缺失，请重新选择后生成 Skill 包。')
  for (const upload of all) {
    const category = item.uploadedResources?.find(row => row.id === upload.id)?.category
    const folder = category === '模板' ? 'templates' : category === '脚本' || uploads.scripts.some(row => row.id === upload.id) ? 'scripts' : category === '参考资料' ? 'references' : 'assets'
    entries.push({ path: `${folder}/${safeName(upload.file.name)}`, data: new Uint8Array(await upload.file.arrayBuffer()) })
  }
  const resourcePaths = entries.map(row => row.path)
  entries.unshift({ path: 'SKILL.md', data: encoder.encode(renderSkillMarkdown(item, resourcePaths)) })
  entries.push({ path: 'manifest.json', data: encoder.encode(JSON.stringify({ mode: 'frontend-preview', skill: item.name, version: item.version, applicationIds: item.applicationIds ?? [], knowledgeBases: selected.map(kb => ({ id: kb.id, name: kb.name, version: kb.version })), uploadedResources: item.uploadedResources ?? [], resources: resourcePaths }, null, 2)) })
  const buildId = `demo-${crypto.randomUUID()}`
  await saveBlobs([{ key: `build:${buildId}`, blob: createZip(entries) }, ...all.map(row => ({ key: `resource:${row.id}`, blob: row.file }))])
  return { buildId, buildOrigin: 'mock' as const }
}
export async function downloadSkillArchive(item: Implementation) {
  if (item.buildOrigin === 'backend') return downloadBuild(item)
  let blob = item.buildId ? await readBlob(`build:${item.buildId}`) : undefined
  if (!blob) {
    const uploads = await restoreSkillUploads(item)
    const build = await buildMockArchive(item, uploads)
    blob = await readBlob(`build:${build.buildId}`)
    if (blob && item.buildId) await saveBlobs([{ key: `build:${item.buildId}`, blob }])
  }
  if (!blob) throw new Error('Skill 包未生成，请先到开发者中心生成。')
  downloadBlob(blob, `${safeName(item.name)}-${safeName(item.version)}-示例.zip`)
}
