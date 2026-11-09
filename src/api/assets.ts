import { authFetch } from './authFetch'
import { downloadBlob } from '@/lib/resourceStorage'
import type { PreviewMetadata, SheetPage } from './knowledgePreview'
import type { TestCase } from '@/types/assistantArtifact'

const root = '/api/assets'

export interface AssetRow {
  id: number; name: string; skill_classes_id: number; class_name: string
  application_identify: string; creator_name: string; visibility: 'private' | 'platform'; can_manage: boolean
  created_time: string; deleted_at: string | null; restore_until: string | null
}
export interface AssetFile { id: number; file_name: string; size_bytes: number }
export interface AssetDetail extends AssetRow { files: AssetFile[] }
export interface AssetOverview { total: number; recycle_count: number; recycle_days: number; classes: { id: number; name: string; count: number; enabled: boolean }[] }
export interface AssetPageResult { items: AssetRow[]; total: number; page: number; pages: number }
export interface AssetStatus { included: boolean; recycled: boolean; asset_id: number | null; files: AssetFile[] }
export interface AssetPreview {
  format: string; viewer: 'pdf' | 'spreadsheet' | 'markdown' | 'text' | 'code' | 'case' | 'unsupported'
  sheets?: PreviewMetadata['sheets']; text?: string; truncated?: boolean
  case_artifact?: { name: string; cases: TestCase[]; groups: { title: string; case_ids: string[] }[] }
}

async function failure(response: Response) {
  const body = await response.json().catch(() => null)
  return new Error(body?.message || (typeof body?.detail === 'string' && body.detail) || '资产操作失败，请重试。')
}

function query(params: Record<string, string | number>) {
  return `?${new URLSearchParams(Object.entries(params).map(([key, value]) => [key, String(value)]))}`
}

function post(body: object): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await authFetch(root + path, { cache: 'no-store', ...options })
  if (!response.ok) throw await failure(response)
  const body = await response.json().catch(() => null)
  if (body?.status !== 'success') throw new Error(body?.message || '资产服务返回无效结果。')
  return body.data
}

async function binary(path: string, options?: RequestInit) {
  const response = await authFetch(root + path, { cache: 'no-store', ...options })
  if (!response.ok || response.headers.get('content-type')?.includes('application/json')) throw await failure(response)
  return response.blob()
}

export function getAssetOverview(signal?: AbortSignal) {
  return request<AssetOverview>('/overview', { signal })
}

export function listAssets(filters: { page: number; search: string; classId?: number; sort: 'asc' | 'desc'; recycle: boolean }, signal?: AbortSignal) {
  const { page, search, classId, sort, recycle } = filters
  return request<AssetPageResult>(recycle ? '/recycle-bin' + query({ page }) : '/list' + query({ page, search, sort,
    ...(classId && { skill_classes_id: classId }) }), { signal })
}

export function getAsset(assetId: number, signal?: AbortSignal) {
  return request<AssetDetail>('/detail' + query({ asset_id: assetId }), { signal })
}

export function previewAsset(assetId: number, fileId: number, signal?: AbortSignal) {
  return request<AssetPreview>('/preview' + query({ asset_id: assetId, file_id: fileId }), { signal })
}

export function previewAssetPdf(assetId: number, fileId: number, signal?: AbortSignal) {
  return binary('/preview-pdf' + query({ asset_id: assetId, file_id: fileId }), { signal })
}

export function previewAssetSheet(assetId: number, fileId: number, sheet: number, offset: number, columnOffset: number, signal?: AbortSignal) {
  return request<SheetPage>('/preview-sheet' + query({ asset_id: assetId, file_id: fileId, sheet_index: sheet, offset, column_offset: columnOffset }), { signal })
}

export async function downloadAsset(assetId: number, file: AssetFile) {
  downloadBlob(await binary('/download' + query({ asset_id: assetId, file_id: file.id })), file.file_name)
}

export async function exportAssets(ids: number[]) {
  downloadBlob(await binary('/export', post({ asset_ids: ids })), '资产清单.csv')
}

const assetActions = { move: '/move-to-recycle-bin', restore: '/restore', delete: '/delete-recycled' } as const
export type AssetAction = keyof typeof assetActions

export function changeAssetState(ids: number[], action: AssetAction) {
  return request<{ changed: number }>(assetActions[action], post({ asset_ids: ids }))
}

export function assetSourceStatus(artifactId: string) {
  return request<AssetStatus>('/source-status' + query({ artifact_id: artifactId }))
}

export function createAsset(data: { artifact_id: string; base_hash: string; name: string; skill_classes_id: number;
  application_identify: string; visibility: 'private' | 'platform' }) {
  return request<AssetStatus>('/create', post(data))
}
