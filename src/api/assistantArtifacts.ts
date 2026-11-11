import { authFetch } from './authFetch'
import { downloadBlob } from '@/lib/resourceStorage'
import type {
  ArtifactFile, ArtifactRevision, AssistantArtifact, FileChanges, OrdinaryArtifact, SheetInfo, SheetPage,
  TestCase, TestCaseArtifact, WordBlock,
} from '@/types/assistantArtifact'

const prefix = '/assistant/artifacts'

interface ArtifactResponse {
  artifact_id: string
  name: string
  file_type: string
  is_test_case: boolean
  grouping_error?: string
  base_hash: string
  cases?: TestCase[]
  groups?: { title: string; case_ids: string[] }[]
  editor?: 'word' | 'sheet' | 'text' | 'download'
  blocks?: WordBlock[]
  sheets?: SheetInfo[]
  text?: string
  encoding?: string
}

type AssetStatus = { included: false } | { included: true; file_sha256: string }

async function errorMessage(response: Response) {
  const body = await response.json().catch(() => null)
  return typeof body?.detail === 'string' ? body.detail : body?.message || '产出物操作失败，请重试。'
}

async function request<T>(path: string, data?: object, signal?: AbortSignal): Promise<T> {
  const response = await authFetch(prefix + path, {
    cache: 'no-store',
    signal,
    ...(data && { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  const result = await response.json().catch(() => null)
  if (result?.status !== 'success') throw new Error(result?.message || '暂时无法读取产出物。')
  return result.data
}

function fromArtifact(row: ArtifactResponse): AssistantArtifact {
  const file = { artifactId: row.artifact_id, baseHash: row.base_hash, name: row.name, fileType: row.file_type }
  if (row.is_test_case && Array.isArray(row.cases) && Array.isArray(row.groups)) {
    return { ...file, editor: 'cases', groupingError: row.grouping_error, cases: row.cases, groups: row.groups.map(group => ({ title: group.title, caseIds: group.case_ids })) }
  }
  if (!row.is_test_case) {
    if (row.editor === 'download') return { ...file, editor: 'download' }
    if (row.editor === 'word' && Array.isArray(row.blocks)) return { ...file, editor: 'word', blocks: row.blocks }
    if (row.editor === 'sheet' && Array.isArray(row.sheets)) return { ...file, editor: 'sheet', sheets: row.sheets }
    if (row.editor === 'text' && typeof row.text === 'string') return { ...file, editor: 'text', text: row.text, encoding: row.encoding || 'utf-8' }
  }
  throw new Error('暂时无法识别产出物预览结构。')
}

export async function openArtifactDemo(kind = 'test_cases') {
  return fromArtifact(await request<ArtifactResponse>('/create-demo', { kind }))
}

export async function getArtifact(artifactId: string, signal?: AbortSignal) {
  return fromArtifact(await request<ArtifactResponse>(`/detail?${new URLSearchParams({ artifact_id: artifactId })}`, undefined, signal))
}

export async function saveArtifact(change: ArtifactRevision & { cases: TestCase[] }): Promise<TestCaseArtifact> {
  const result = fromArtifact(await request<ArtifactResponse>('/save-content', {
    artifact_id: change.artifactId, base_hash: change.baseHash, cases: change.cases,
  }))
  if (result.editor !== 'cases') throw new Error('保存响应与测试案例格式不匹配。')
  return result
}

export async function saveOrdinaryArtifact(revision: ArtifactRevision, changes: FileChanges): Promise<OrdinaryArtifact> {
  const result = fromArtifact(await request<ArtifactResponse>('/save-content', {
    artifact_id: revision.artifactId, base_hash: revision.baseHash, ...changes,
  }))
  if (result.editor === 'cases' || result.editor === 'download') throw new Error('保存响应与文件格式不匹配。')
  return result
}

export function getArtifactSheet(revision: ArtifactRevision, index: number, offset: number, columnOffset: number, signal: AbortSignal) {
  const query = new URLSearchParams({ artifact_id: revision.artifactId, base_hash: revision.baseHash,
    sheet_index: String(index), offset: String(offset), column_offset: String(columnOffset) })
  return request<SheetPage>(`/sheet?${query}`, undefined, signal)
}

export function artifactAssetStatus(artifactId: string) {
  return request<AssetStatus>(`/asset-status?${new URLSearchParams({ artifact_id: artifactId })}`)
}

export function archiveArtifact(revision: ArtifactRevision, name: string, application: string) {
  return request<Extract<AssetStatus, { included: true }>>('/submit-to-assets', {
    artifact_id: revision.artifactId, base_hash: revision.baseHash, name, application_identify: application,
  })
}

export async function readArtifactFile(artifact: ArtifactFile, archived = false, signal?: AbortSignal) {
  const query = new URLSearchParams({ artifact_id: artifact.artifactId, base_hash: artifact.baseHash })
  if (archived) query.set('archived', 'true')
  const response = await authFetch(`${prefix}/download?${query}`, { cache: 'no-store', signal })
  if (!response.ok || !response.headers.get('content-disposition')?.startsWith('attachment')) {
    throw new Error(await errorMessage(response))
  }
  return response.blob()
}

export async function exportArtifact(artifact: ArtifactFile, archived = false) {
  downloadBlob(await readArtifactFile(artifact, archived), `${artifact.name}.${artifact.fileType}`)
}
