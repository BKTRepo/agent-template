import type { KnowledgeBase } from '@/types/developer'
import { knowledgeFileLimits } from './skillForm'

export function knowledgeFileSizeError(files: { size: number }[]): string {
  return files.reduce((total, file) => total + file.size, 0) > knowledgeFileLimits.maxTotalBytes!
    ? '知识库文件总大小不能超过 200 MB' : ''
}

/** Immutable business-content snapshot; progress, version and change notes are excluded. */
export function knowledgeEditSnapshot(form: Pick<KnowledgeBase, 'name' | 'description' | 'tag' | 'scope' | 'applicationIds' | 'files'>): string {
  return JSON.stringify([
    form.name.trim(), form.description.trim(), form.tag.trim(), form.scope,
    (form.applicationIds ?? []).map(id => id.trim()).sort(),
    // Existing IDs identify retained documents; new IDs identify pending replacements/uploads.
    form.files.map(file => JSON.stringify([file.id, file.name])).sort(),
  ])
}

/** Validate create metadata before uploading any conversion jobs. */
export function knowledgeCreationErrors(form: { description: string; tag: string; applicationIds?: string[] }): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!form.description.trim()) errors.description = '请填写知识库描述'
  if (!form.tag.trim()) errors.tag = '请选择知识库标签'
  if (form.applicationIds?.length !== 1 || !form.applicationIds[0]?.trim()) errors.applicationIds = '请选择所属应用'
  return errors
}
