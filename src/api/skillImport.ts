import { DeveloperCenterError, request } from './developerCenter'

export interface ImportLimits { max_batch_bytes: number; max_file_bytes: number; max_skill_bytes: number; max_files: number; max_skills: number; max_skill_files: number; expires_hours: number }
export interface ImportSelection { item_id: string; name: string; class_id: number; application_paso: string; expected_revision?: number }
export interface ImportItem {
  item_id: string; source_path?: string; source_size?: number; root_path: string; default_name: string; description: string; valid: boolean
  status: 'READY' | 'INVALID' | 'SUCCEEDED' | 'FAILED'; errors: string[]; skill_id: number | null; revision?: number
  attachments: { path: string; size: number }[]; selection: Partial<ImportSelection>
}
export interface ImportBatch { import_id: string; expires_at: string; expired: boolean; limits: ImportLimits; items: ImportItem[] }
export interface ImportUpload { file: File; path: string }
export function getImportLimits() { return request<ImportLimits>('/skills/import/get-limits') }
// Upload-time validation/extraction; files and receipts stay in the OS temp directory.
export function stageSkillImport(files: ImportUpload[], mode: 'file' | 'directory' | 'zip', selectedRoot?: string, replacesImportId?: string) {
  const data = new FormData()
  data.append('manifest', JSON.stringify({ upload_mode: mode, files: files.map((row, index) => ({ index, path: row.path })),
    ...(selectedRoot !== undefined ? { selected_root: selectedRoot } : {}), ...(replacesImportId ? { replaces_import_id: replacesImportId } : {}) }))
  files.forEach(row => data.append('files', row.file, row.file.name))
  return request<ImportBatch>('/skills/import/stage', { method: 'POST', body: data })
}
export function discardSkillImport(importId: string) {
  return request('/skills/import/discard', { method: 'POST', body: JSON.stringify({ import_id: importId }) })
}
export async function prepareSkillImport(files: ImportUpload[], mode: 'file' | 'directory' | 'zip', limits?: ImportLimits, replacesImportId?: string) {
  if (!files.length) throw new Error('请选择技能定义文件、文件夹或ZIP。')
  if (limits) {
    const oversized = files.find(row => row.file.size > limits.max_file_bytes)
    if (oversized) throw new Error(`“${oversized.path}”超过单文件大小限制（${(limits.max_file_bytes / 1024 / 1024).toFixed(0)} MiB）。`)
    if (files.length > limits.max_files || files.reduce((sum, row) => sum + row.file.size, 0) > limits.max_batch_bytes) {
      throw new Error(`一次最多 ${limits.max_files} 个文件，总大小不超过 ${(limits.max_batch_bytes / 1024 / 1024).toFixed(0)} MiB。`)
    }
  }
  if (mode === 'zip' && (files.length !== 1 || !files[0].file.name.toLowerCase().endsWith('.zip'))) {
    throw new Error('ZIP导入每次请选择一个ZIP压缩包。')
  }
  if (mode === 'directory' && !files.some(row => row.path.split('/').pop()?.toLowerCase() === 'skill.md' || row.path.toLowerCase().endsWith('.zip'))) {
    throw new Error('所选文件夹中未找到SKILL.md或ZIP技能包。请选择包含技能定义文件或技能压缩包的目录。')
  }
  if (mode === 'file' && (files.length !== 1 || files[0].file.name.toLowerCase() !== 'skill.md')) {
    throw new Error('单文件导入只支持SKILL.md，请选择技能定义文件或ZIP。')
  }
  // 在构造请求前检查所选原文件是否仍可读取，避免把本地文件失效当作服务故障。
  for (const row of files) {
    try { await row.file.slice(0, 1).arrayBuffer() }
    catch { throw new Error(`无法读取“${row.path}”。请确认文件仍然存在且可访问，然后重新选择文件夹。`) }
  }
  const data = new FormData()
  data.append('manifest', JSON.stringify({ upload_mode: mode, files: files.map((row, index) => ({ index, path: row.path })), ...(replacesImportId ? { replaces_import_id: replacesImportId } : {}) }))
  files.forEach(row => data.append('files', row.file, row.file.name))
  try {
    return await request<ImportBatch>('/skills/import/prepare', { method: 'POST', body: data })
  } catch (error) {
    if (error instanceof DeveloperCenterError && error.statusCode === 0) {
      throw new DeveloperCenterError('上传未完成。请重新选择文件夹后重试；目录中的文件发生变动、文件读取失败或连接中断都可能导致此问题。', 0)
    }
    throw error
  }
}
export function confirmSkillImport(importId: string, items: ImportSelection[]) {
  return request<ImportBatch>('/skills/import/confirm', { method: 'POST', body: JSON.stringify({ import_id: importId, items }) })
}
export function restartSkillImport(importId: string) {
  return request<ImportBatch>('/skills/import/restart', { method: 'POST', body: JSON.stringify({ import_id: importId }) })
}
export function checkSkillImportNames(importId: string, items: { item_id: string; name: string }[]) {
  return request<{ valid: boolean; errors: Record<string, string[]> }>('/skills/import/check-names', {
    method: 'POST', body: JSON.stringify({ import_id: importId, items }),
  })
}
export function getSkillImport(importId: string) {
  return request<ImportBatch>(`/skills/import/status?${new URLSearchParams({ import_id: importId })}`)
}

interface DroppedEntry {
  name: string; isFile: boolean; isDirectory: boolean
  file: (success: (file: File) => void, failure: (error: DOMException) => void) => void
  createReader: () => { readEntries: (success: (entries: DroppedEntry[]) => void, failure: (error: DOMException) => void) => void }
}
export async function readDroppedSkills(items: DataTransferItemList, maxFiles: number): Promise<{ files: ImportUpload[]; directory: boolean }> {
  const entries = Array.from(items).filter(item => item.kind === 'file').map(item => item.webkitGetAsEntry() as DroppedEntry | null)
  if (entries.some(entry => !entry)) throw new Error('无法读取拖入的内容，请使用选择文件或选择文件夹。')
  const files: ImportUpload[] = []
  async function walk(entry: DroppedEntry, prefix: string): Promise<void> {
    const path = prefix + entry.name
    if (path.length > 255) throw new Error('目录路径过长，请缩短目录名称。')
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) => entry.file(resolve, reject))
      files.push({ file, path })
      if (files.length > maxFiles) throw new Error(`一次最多上传 ${maxFiles} 个文件。`)
    } else if (entry.isDirectory) {
      const reader = entry.createReader()
      while (true) {
        const batch = await new Promise<DroppedEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
        if (!batch.length) break
        for (const child of batch) await walk(child, path + '/')
      }
    }
  }
  for (const entry of entries) await walk(entry!, '')
  return { files, directory: entries.some(entry => entry?.isDirectory) }
}
