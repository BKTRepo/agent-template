import type { ImplementationForm } from '@/types/developer'
export function copySkillForm(form: ImplementationForm, version: string): ImplementationForm {
  const result = { classId: form.classId === 'SKILL-API-003' ? 'SKILL-POINT-005' : form.classId, name: form.name.trim(), technicalName: form.technicalName, system: form.system, team: form.team ?? '', version, modelTier: form.modelTier, description: form.description, instructions: form.instructions, compatibility: form.compatibility ?? '', applicationIds: [...(form.applicationIds ?? [])], resourceIds: [...form.resourceIds], resourceUsage: form.resourceUsage ?? '', knowledgeBases: form.knowledgeBases?.map(row => ({ ...row })) ?? [], uploadedResources: form.uploadedResources?.map(row => ({ ...row })) ?? [], skillMarkdown: form.skillMarkdown }
  if (result.skillMarkdown) result.skillMarkdown = syncMarkdownFields(result)
  return result
}
export function markdownBody(value: string) {
  const markdown = value.replaceAll('\r\n', '\n')
  if (!markdown.startsWith('---\n')) return markdown.trim()
  const end = markdown.indexOf('\n---', 4)
  if (end < 0) throw new Error('Skill 定义的 Markdown 头部未正确结束。')
  return markdown.slice(end + 4).trim()
}
function syncMarkdownFields(form: ImplementationForm) {
  const md = withSystemVersion(form.skillMarkdown!, form.version)
  const end = md.indexOf('\n---', 4)
  let header = md.slice(4, end)
  for (const [key, value] of [['name',form.technicalName],['display_name',form.name],['description',form.description],['compatibility',form.compatibility ?? '']]) {
    const expression = new RegExp(`^${key}\\s*:.*$`, 'gm')
    header = expression.test(header) ? header.replace(expression, () => `${key}: ${JSON.stringify(value)}`) : `${header}\n${key}: ${JSON.stringify(value)}`
  }
  let body = form.instructions
  const heading = /^## 资源使用说明[^\n]*\n/m.exec(body)
  if (heading) {
    const start = heading.index + heading[0].length
    const tail = body.slice(start)
    const nextHeading = /^## /m.exec(tail)
    body = body.slice(0, start) + (form.resourceUsage || '无挂载资源') + '\n\n' + (nextHeading ? tail.slice(nextHeading.index) : '')
  }
  const resourceHeading = /^## 挂载资源[^\n]*\n/m.exec(body)
  if (resourceHeading) {
    const start = resourceHeading.index + resourceHeading[0].length
    const tail = body.slice(start)
    const nextHeading = /^## /m.exec(tail)
    const names = [...(form.knowledgeBases?.map(row => row.name) ?? []), ...(form.uploadedResources?.map(row => row.name) ?? [])]
    body = body.slice(0, start) + (names.map(name => `- ${name}`).join('\n') || '无') + '\n\n' + (nextHeading ? tail.slice(nextHeading.index) : '')
  }
  return `---\n${header}\n---\n\n${body}`
}
export function withSystemVersion(markdown: string, version: string) {
  markdown = markdown.replaceAll('\r\n', '\n')
  if (!markdown.startsWith('---\n')) return `---\nversion: ${JSON.stringify(version)}\n---\n\n${markdown}`
  const end = markdown.indexOf('\n---', 4)
  if (end < 0) throw new Error('Skill 定义的 Markdown 头部未正确结束。')
  const header = markdown.slice(4, end)
  const next = /^version\s*:/m.test(header) ? header.replace(/^version\s*:.*$/gm, `version: ${JSON.stringify(version)}`) : `${header}\nversion: ${JSON.stringify(version)}`
  return `---\n${next}${markdown.slice(end)}`
}
