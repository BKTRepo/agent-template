import type { ImplementationForm, UploadedResource } from '@/types/developer'

const normalizedName = (value: string) => value.trim().normalize('NFKC').trim().toLowerCase()
export const resourceExtensions = ['.py', '.js', '.sh', '.bash', '.ps1', '.zip', '.whl', '.gz', '.tgz', '.tar', '.md', '.txt', '.json', '.csv', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']
// 定稿中“资源上传”明确允许的 Skill 附件格式。
export const skillResourceExtensions = ['.py', '.js', '.md', '.xlsx', '.docx', '.png', '.jpg', '.jpeg']
export const documentExtensions = ['.pdf', '.doc', '.docx', '.md', '.txt', '.xls', '.xlsx', '.json']
export const resourceCategories = ['参考资料', '模板', '静态资源', '脚本'] as const
export interface ResourceFileLimits { maxFileBytes?: number; maxFiles?: number; maxTotalBytes?: number }
export const skillResourceLimits: ResourceFileLimits = { maxFileBytes: 50 * 1024 * 1024, maxTotalBytes: 50 * 1024 * 1024 }
// 调试文档的格式独立于资源上传，但沿用 50MB 单文件、总量限制；最多 10 份。
export const debugDocumentLimits: ResourceFileLimits = { ...skillResourceLimits, maxFiles: 10 }
// 20261016 调整说明明确取消知识库文件大小控制。
export const knowledgeFileLimits: ResourceFileLimits = {}
export const knowledgeExtensions = ['.pdf', '.doc', '.docx', '.md', '.txt', '.xls', '.xlsx']
export function validateSkillForm(form: ImplementationForm, existing: { id: string; name: string; pendingChanges?: { name: string } }[], id?: string, draft = false) {
  const errors: Record<string, string> = {}
  void draft
  if (!['SKILL-POINT-005','SKILL-CASE-001','SKILL-BUG-004','SKILL-REPORT-006','SKILL-DATA-002','SKILL-UI-007'].includes(form.classId)) errors.classId = '请选择所属技能大类'
  if (!form.name.trim()) errors.name = '技能名称不能为空'
  else if (existing.some(item => item.id !== id && (normalizedName(item.name) === normalizedName(form.name) || (item.pendingChanges && normalizedName(item.pendingChanges.name) === normalizedName(form.name))))) errors.name = '该技能名称已存在，请更换'
  if (form.name.trim().length > 128) errors.name = '技能名称最长 128 个字符'
  if (!form.description?.trim()) errors.description = '请填写描述'
  if ((form.description?.length ?? 0) > 1024) errors.description = '描述最长 1024 个字符'
  // 草稿可保存未填写完的指令和使用说明；进入调试前执行完整校验。
  if (!form.instructions.trim()) errors.instructions = '请填写执行指令'
  if (form.instructions.length > 100000) errors.instructions = '执行指令最长 100000 个字符'
  if ((form.resourceIds.length > 0 || (form.uploadedResources?.length ?? 0) > 0) && !form.resourceUsage?.trim()) errors.resourceUsage = '已选择挂载知识库或上传资源，请填写资源使用说明'
  if (form.uploadedResources?.some(file => !resourceCategories.includes(file.category!))) errors.uploadedResources = '请为每份上传资源选择用途分类'
  if (form.uploadedResources?.some(file => file.size > skillResourceLimits.maxFileBytes!) || (form.uploadedResources ?? []).reduce((sum, file) => sum + file.size, 0) > skillResourceLimits.maxTotalBytes!) errors.uploadedResources = '单个资源文件及资源总大小均不能超过 50 MB'
  if ((form.applicationIds?.length ?? 0) > 1) errors.applicationIds = '请选择一个所属应用'
  if ((form.resourceUsage?.length ?? 0) > 10000) errors.resourceUsage = '资源使用说明最长 10000 个字符'
  if ((form.compatibility?.length ?? 0) > 500) errors.compatibility = '运行环境要求最长 500 个字符'
  return errors
}
export function validateResourceFiles(files: File[], existing: UploadedResource[], extensions = resourceExtensions, limits = skillResourceLimits) {
  const accepted: File[] = []
  const errors: string[] = []
  const names = new Set(existing.map(file => normalizedName(file.name)))
  let total = existing.reduce((sum, file) => sum + file.size, 0)
  for (const file of files) {
    if (!extensions.some(extension => file.name.toLowerCase().endsWith(extension))) { errors.push(`${file.name}：不支持此文件类型`); continue }
    if (/[\\/<>:"|?*\x00-\x1f\x7f]/.test(file.name) || /[. ]$/.test(file.name) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])\./i.test(file.name)) { errors.push(`${file.name}：文件名无效`); continue }
    if (file.size === 0) { errors.push(`${file.name}：资源文件为空`); continue }
    if (names.has(normalizedName(file.name))) { errors.push(`${file.name}：同名资源已存在，请先移除旧文件`); continue }
    if (limits.maxFileBytes !== undefined && file.size > limits.maxFileBytes) { errors.push(`${file.name}：单个文件不能超过 ${limits.maxFileBytes / 1024 / 1024} MB`); continue }
    if (limits.maxFiles !== undefined && existing.length + accepted.length >= limits.maxFiles) { errors.push(`最多上传 ${limits.maxFiles} 个文件`); continue }
    if (limits.maxTotalBytes !== undefined && total + file.size > limits.maxTotalBytes) { errors.push(`总大小不能超过 ${limits.maxTotalBytes / 1024 / 1024} MB`); continue }
    accepted.push(file); names.add(normalizedName(file.name)); total += file.size
  }
  return { accepted, errors }
}
