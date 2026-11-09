import { authFetch } from './authFetch'
import { knowledgeRequest } from './knowledge'

export interface PreviewMetadata {
  id: number; filename: string; generation: number; content_hash: string; markdown: string
  viewer: 'pdf' | 'spreadsheet' | 'markdown' | 'text' | 'unsupported'; format: string
  sheets: { index: number; name: string; rows: number; columns: number }[]
}
export interface SheetCell { value: string | number | boolean | null; formula: boolean; bold: boolean; color?: string; background?: string; align?: 'left' | 'center' | 'right' }
export interface SheetPage {
  sheet_index: number; name: string; total_rows: number; total_columns: number; offset: number; column_offset: number
  columns: string[]; rows: SheetCell[][]; merges: number[][]; streaming: boolean; formula_note: string
}
export async function getPreviewMetadata(kbId: string, docId: string, signal?: AbortSignal): Promise<PreviewMetadata> {
  return (await knowledgeRequest<PreviewMetadata>(`/knowledge-bases/documents/preview?${new URLSearchParams({ kb_id: kbId, doc_id: docId })}`, { signal })).data
}
export async function getPreviewBinary(kbId: string, docId: string, generation: number | undefined, pdf: boolean, signal?: AbortSignal) {
  const query = new URLSearchParams({ kb_id: kbId, doc_id: docId })
  if (generation !== undefined) query.set('generation', String(generation))
  const response = await authFetch(`/knowledge-bases/documents/${pdf ? 'preview-pdf' : 'download'}?${query}`, { signal, cache: 'no-store' })
  if (!response.ok || response.headers.get('content-type')?.includes('application/json')) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.message || '文件预览加载失败，请重试。')
  }
  return response.blob()
}
export async function getSheetPage(kbId: string, docId: string, generation: number, sheet: number, offset: number, columnOffset: number, signal?: AbortSignal) {
  return (await knowledgeRequest<SheetPage>(`/knowledge-bases/documents/preview-sheet?${new URLSearchParams({
    kb_id: kbId, doc_id: docId, generation: String(generation), sheet_index: String(sheet), offset: String(offset), limit: '100', column_offset: String(columnOffset), column_limit: '50',
  })}`, { signal })).data
}
