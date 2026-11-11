import { useAssistantPageObject } from '@/stores/assistantContextStore'
import { useEffect, useState } from 'react'
import { LayoutGrid, Layers3, Trash2, List, Code2, Database, FileText, Target, CheckCircle2 } from 'lucide-react'
import { changeAssetState, downloadAsset, exportAssets, getAsset, getAssetOverview, listAssets, type AssetAction, type AssetOverview, type AssetPageResult } from '@/api/assets'
import { getKnowledgeMetadata } from '@/api/knowledge'
import AssetPreviewDialog from '@/components/assets/AssetPreviewDialog'
import ListPagination from '@/components/common/ListPagination'
import Dialog from '@/components/developer/Dialog'
import '@/components/assets/assets.css'

const categoryIcons = [LayoutGrid, List, Code2, Database, FileText, Target, CheckCircle2]

const emptyPage: AssetPageResult = { items: [], total: 0, page: 1, pages: 1 }
const formatTime = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
const actionLabels = { move: '移入回收站', restore: '恢复', delete: '彻底删除' } as const

export default function AssetsPage() {
  const [overview, setOverview] = useState<AssetOverview>()
  const [result, setResult] = useState(emptyPage)
  const [applications, setApplications] = useState<Record<string, string>>({})
  const [recycle, setRecycle] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [filters, setFilters] = useState<{ page: number; search: string; classId?: number; sort: 'asc' | 'desc' }>({ page: 1, search: '', sort: 'desc' })
  const [selected, setSelected] = useState<number[]>([])
  const [preview, setPreview] = useState<number>()
  const [pending, setPending] = useState<{ ids: number[]; action: AssetAction }>()
  useAssistantPageObject('assets', 'asset', preview)
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [overviewError, setOverviewError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    const update = () => setRefresh(value => value + 1)
    window.addEventListener('asset-collection-changed', update)
    return () => window.removeEventListener('asset-collection-changed', update)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getKnowledgeMetadata(controller.signal).then(value => {
      if (!controller.signal.aborted) setApplications(Object.fromEntries(value.applications.map(row => [row.id, row.name])))
    }).catch(() => {}) // Application codes remain available if the external catalog is down.
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getAssetOverview(controller.signal).then(value => {
      if (!controller.signal.aborted) { setOverview(value); setOverviewError('') }
    }).catch(reason => { if (!controller.signal.aborted) setOverviewError(reason.message) })
    return () => controller.abort()
  }, [refresh])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setSelected([]); setError('')
    void listAssets({ ...filters, recycle }, controller.signal).then(value => {
      if (!controller.signal.aborted) setResult(value)
    }).catch(reason => {
      if (!controller.signal.aborted) { setError(reason.message); setResult(emptyPage) }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [filters, recycle, refresh])

  async function run(action: () => Promise<void>) {
    if (busy) return
    setBusy(true); setError(''); setNotice('')
    try { await action() }
    catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }

  function reset() {
    setKeyword(''); setFilters({ page: 1, search: '', sort: 'desc' })
  }

  function toggleRecycle() {
    reset(); setRecycle(!recycle); setNotice('')
  }

  const locked = busy || loading
  const label = recycle ? '回收站' : overview?.classes.find(row => row.id === filters.classId)?.name ?? '全部资产'
  const eligible = result.items.filter(row => recycle || row.can_manage).map(row => row.id)
  const selectedForChange = selected.filter(id => eligible.includes(id))

  return <div className="assets-page">
    <div className="asset-page-actions"><button className="button" disabled={busy} onClick={toggleRecycle}>
      {recycle ? '返回资产列表' : <><Trash2 size={15} />回收站 {overview?.recycle_count ?? ''}</>}
    </button></div>
    {!recycle && overview && <section className="asset-overview" aria-label="资产概览">
      {[{ id: undefined, name: '全部资产', count: overview.total }, ...overview.classes].map((row, index) => <button type="button"
        key={row.id ?? 'all'} aria-pressed={filters.classId === row.id} disabled={busy}
        onClick={() => setFilters({ ...filters, classId: row.id, page: 1 })}>
        <span className="asset-overview-icon">{(() => { const Icon = categoryIcons[index] ?? Layers3; return <Icon size={16} /> })()}</span><span className="asset-overview-label">{row.name}</span><strong>{row.count.toLocaleString('zh-CN')}</strong>
      </button>)}
    </section>}
    {overviewError && <p role="alert" className="error-banner">{overviewError} <button className="button small" onClick={() => setRefresh(value => value + 1)}>重试</button></p>}
    <section className="surface asset-list" aria-label={label}>
      <h2>{label}</h2>
      {!recycle && <form className="management-filters" onSubmit={event => { event.preventDefault(); setFilters({ ...filters, search: keyword.trim(), page: 1 }) }}>
        <input aria-label="搜索资产名称或创建人" placeholder="搜索资产名称 / 创建人" maxLength={128} value={keyword} onChange={event => setKeyword(event.target.value)} />
        <button className="button primary" disabled={busy}>搜索</button><button type="button" className="button" disabled={busy} onClick={reset}>重置</button>
      </form>}
      {selected.length > 0 && <div className="asset-bulk"><span>已选 {selected.length} 项</span>
        {!recycle && <button className="button small" disabled={locked} onClick={() => void run(() => exportAssets(selected))}>批量导出</button>}
        <button className="button small" disabled={locked || selectedForChange.length !== selected.length}
          onClick={() => setPending({ ids: selectedForChange, action: recycle ? 'restore' : 'move' })}>{recycle ? '恢复' : '移入回收站'}</button>
        {recycle && <button className="button small" disabled={locked} onClick={() => setPending({ ids: selected, action: 'delete' })}>彻底删除</button>}
        <button className="button small" disabled={locked} onClick={() => setSelected([])}>取消选择</button>
      </div>}
      {notice && <p role="status" className="helper-text">{notice}</p>}
      {error && !pending && <p role="alert" className="error-banner">{error} <button className="button small" onClick={() => setRefresh(value => value + 1)}>重试</button></p>}
      <div className="asset-table-wrap" aria-busy={loading}><table className="asset-table"><thead><tr>
        <th><input type="checkbox" aria-label="选择本页资产" disabled={locked || !result.items.length}
          checked={result.items.length > 0 && selected.length === result.items.length}
          onChange={event => setSelected(event.target.checked ? result.items.map(row => row.id) : [])} /></th>
        <th scope="col">资产名称</th><th scope="col">资产类型</th><th scope="col">内容数量</th><th scope="col">所属应用</th><th scope="col">创建人</th>
        {recycle ? <><th scope="col">回收时间</th><th scope="col">可恢复至</th></> : <th scope="col" aria-sort={filters.sort === 'asc' ? 'ascending' : 'descending'}>
          <button type="button" className="asset-text-button" disabled={busy} onClick={() => setFilters({ ...filters, page: 1, sort: filters.sort === 'asc' ? 'desc' : 'asc' })}>创建时间 {filters.sort === 'asc' ? '↑' : '↓'}</button></th>}
        <th scope="col">操作</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={recycle ? 9 : 8} className="empty-table">正在加载资产…</td></tr>
          : !result.items.length ? <tr><td colSpan={recycle ? 9 : 8} className="empty-table">{recycle ? '回收站暂无可恢复的资产' : '没有匹配的资产'}</td></tr>
          : result.items.map(row => <tr key={row.id}>
            <td><input type="checkbox" aria-label={`选择 ${row.name}`} disabled={locked} checked={selected.includes(row.id)}
              onChange={event => setSelected(previous => event.target.checked ? [...previous, row.id] : previous.filter(id => id !== row.id))} /></td>
            <td>{recycle ? row.name : <button className="asset-text-button" onClick={() => setPreview(row.id)}>{row.name}</button>}</td>
            <td>{row.class_name}</td><td>{row.content_quantity}</td><td>{applications[row.application_identify] || row.application_identify}</td><td>{row.creator_name}</td>
            {recycle ? <><td>{formatTime(row.deleted_at!)}</td><td>{formatTime(row.restore_until!)}</td></> : <td>{formatTime(row.created_time)}</td>}
            <td><div className="asset-row-actions">{recycle ? <>
              <button className="button small" disabled={locked} onClick={() => setPending({ ids: [row.id], action: 'restore' })}>恢复</button>
              <button className="button small" disabled={locked} onClick={() => setPending({ ids: [row.id], action: 'delete' })}>彻底删除</button>
            </> : <>
              <button className="button small" disabled={locked} onClick={() => setPreview(row.id)}>预览</button>
              <button className="button small" disabled={locked} onClick={() => void run(async () => {
                const asset = await getAsset(row.id)
                if (asset.files.length === 1) await downloadAsset(row.id, asset.files[0])
                else setPreview(row.id)
              })}>导出</button>
              <button className="button small" disabled={locked || !row.can_manage} title={row.can_manage ? undefined : '仅创建人可移入回收站'}
                onClick={() => setPending({ ids: [row.id], action: 'move' })}>移入回收站</button>
            </>}</div></td>
          </tr>)}
      </tbody></table></div>
      <ListPagination total={result.total} page={result.page} pages={result.pages} busy={locked} label="资产分页"
        onPageChange={page => setFilters({ ...filters, page })} />
    </section>
    {preview && <AssetPreviewDialog key={preview} assetId={preview} onClose={() => setPreview(undefined)} />}
    {pending && <Dialog title={actionLabels[pending.action]} busy={busy} onClose={() => { setPending(undefined); setError('') }}
      footer={<><button className="button" disabled={busy} onClick={() => { setPending(undefined); setError('') }}>取消</button>
        <button className="button primary" disabled={busy} onClick={() => void run(async () => {
          const result = await changeAssetState(pending.ids, pending.action)
          setPending(undefined); setNotice(`已${actionLabels[pending.action]} ${result.changed} 项资产`)
          setRefresh(value => value + 1)
        })}>{pending.action === 'move' ? '确认移入' : `确认${actionLabels[pending.action]}`}</button></>}>
      <p>{actionLabels[pending.action]}所选 {pending.ids.length} 项资产？
        {pending.action === 'delete' ? '彻底删除后无法恢复。' : pending.action === 'move' && `回收站保留 ${overview?.recycle_days ?? 30} 天。`}</p>
      {error && <p className="error-banner" role="alert">{error}</p>}
    </Dialog>}
  </div>
}
