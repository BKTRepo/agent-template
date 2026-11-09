import { useCallback, useEffect, useRef, useState } from 'react'
import SkillCatalogGroup from '@/components/skills/SkillCatalogGroup'
import Dialog from '@/components/developer/Dialog'
import DebugDialog from '@/components/developer/DebugDialog'
import SearchSelect from '@/components/developer/SearchSelect'
import { downloadBlob } from '@/lib/resourceStorage'
import { getCatalogClass, getCatalogMetadata, getCatalogSkill, downloadCatalogSkill, prepareCatalogTest } from '@/api/skillCatalog'
import type { CatalogMetadata, ClassDefinition } from '@/api/skillCatalog'
import { useAuthStore } from '@/stores/authStore'
import { useAccessStore } from '@/stores/accessStore'
import type { Implementation } from '@/types/developer'

const emptyFilters = { name: '', classId: '', system: '', maintainer: '' }
const emptyMetadata: CatalogMetadata = { skill_classes: [], applications: [], maintainers: [] }
export default function SkillsPage() {
  const token = useAuthStore(state => state.session?.token)
  const actor = useAccessStore(state => state.actor.id)
  const [filters, setFilters] = useState(emptyFilters)
  const [applied, setApplied] = useState(emptyFilters)
  const [metadata, setMetadata] = useState(emptyMetadata)
  const [classTotals, setClassTotals] = useState<Record<string, number>>({})
  const onTotal = useCallback((id: string, total: number) => setClassTotals(previous => ({ ...previous, [id]: total })), [])
  const [reload, setReload] = useState(0)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string[]>([])
  const [detail, setDetail] = useState<Implementation | null>(null)
  const [classDetail, setClassDetail] = useState<ClassDefinition | null>(null)
  const [debugItem, setDebugItem] = useState<Implementation | null>(null)
  const [busy, setBusy] = useState<string>()
  const [error, setError] = useState('')
  const generation = useRef(0)
  useEffect(() => {
    generation.current++
    setDetail(null); setClassDetail(null); setDebugItem(null); setBusy(undefined)
    setMetadata(emptyMetadata); setClassTotals({}); setExpanded([]); setFilters(emptyFilters); setApplied(emptyFilters)
    return () => { generation.current++ }
  }, [token, actor])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setClassTotals({})
    void getCatalogMetadata(controller.signal).then(next => {
      if (controller.signal.aborted) return
      setMetadata(next); setExpanded(next.skill_classes.map(row => row.id))
    }).catch(reason => { if (!controller.signal.aborted) { setMetadata(emptyMetadata); setError((reason as Error).message) } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [reload, token, actor])
  async function action(key: string, work: () => Promise<void>) {
    const current = generation.current
    setBusy(key); setError('')
    try { await work() } catch (reason) { if (current === generation.current) setError((reason as Error).message) }
    finally { if (current === generation.current) setBusy(undefined) }
  }
  async function inspect(item: Implementation, test = false) {
    const current = generation.current
    await action(item.id, async () => {
      const value = test ? await prepareCatalogTest(item.id) : await getCatalogSkill(item.id)
      if (current === generation.current) { if (test) setDebugItem(value); else setDetail(value) }
    })
  }
  async function inspectClass(id: string) {
    const current = generation.current
    await action(`class-${id}`, async () => { const value = await getCatalogClass(id); if (current === generation.current) setClassDetail(value) })
  }
  async function download(item: Implementation) {
    const current = generation.current
    await action(item.id, async () => {
      await downloadCatalogSkill(item)
      const updated = await getCatalogSkill(item.id)
      if (current === generation.current) {
        setDetail(previous => previous?.id === updated.id ? updated : previous)
      }
    })
  }
  const classes = metadata.skill_classes.filter(row => !applied.classId || row.id === applied.classId)
  const noResults = classes.length === 0 || classes.every(row => classTotals[row.id] === 0)
  function applyFilters(next: typeof emptyFilters) { setClassTotals({}); setApplied({ ...next }) }
  const applicationName = (item: Implementation) => (item.applicationIds ?? []).map(id => id === '*' ? '全应用适用' : metadata.applications.find(row => row.id === id)?.name || id).join('、') || '未关联应用'
  return <>
    <form className="surface catalog-filters" onSubmit={event => { event.preventDefault(); applyFilters(filters) }}>
      <input aria-label="技能名称模糊搜索" placeholder="名称模糊搜索" value={filters.name} onChange={event => setFilters(previous => ({ ...previous, name: event.target.value }))} />
      <select aria-label="技能类" value={filters.classId} onChange={event => setFilters(previous => ({ ...previous, classId: event.target.value }))}><option value="">全部技能大类</option>{metadata.skill_classes.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
      <SearchSelect label="筛选所属应用" value={filters.system} options={metadata.applications.filter(row => row.id !== '*')} placeholder="全部应用" onChange={value => setFilters(previous => ({ ...previous, system: value }))} />
      <SearchSelect label="维护人" value={filters.maintainer} options={metadata.maintainers} placeholder="全部维护人" onChange={value => setFilters(previous => ({ ...previous, maintainer: value }))} />
      <button className="button primary" disabled={loading}>搜索</button><button type="button" className="button" disabled={loading} onClick={() => { setFilters(emptyFilters); applyFilters(emptyFilters) }}>重置</button>
    </form>
    {error && <p className="error-banner" role="alert">{error}<button className="button small" onClick={() => setReload(value => value + 1)}>重新加载</button></p>}
    {loading && <p className="helper-text" role="status">正在加载技能目录…</p>}
    {!loading && !error && noResults && <p className="helper-text" role="status">暂无符合条件的已发布实现类</p>}
    <div className="skill-group-list" aria-busy={loading}>{!loading && classes.map(skillClass => <SkillCatalogGroup
      key={`${token}:${actor}:${JSON.stringify(applied)}:${skillClass.id}`} skillClass={skillClass} filters={applied} reload={reload}
      expanded={expanded.includes(skillClass.id)} onToggle={() => setExpanded(previous => previous.includes(skillClass.id) ? previous.filter(id => id !== skillClass.id) : [...previous, skillClass.id])}
      busy={busy} applicationName={applicationName} onInspect={inspect} onInspectClass={inspectClass} onDownload={download} onTotal={onTotal}
    />)}</div>
    {detail && <Dialog wide title={`实现类详情 · ${detail.name}`} onClose={() => setDetail(null)} footer={<><button className="button" onClick={() => setDetail(null)}>关闭</button><button className="button primary" disabled={!!busy || !detail.buildId} onClick={() => download(detail)}>下载技能 ZIP</button></>}><dl className="constraint-details">{[
      ['所属技能大类', metadata.skill_classes.find(row => row.id === detail.classId)?.name || detail.classId], ['所属应用', applicationName(detail)], ['维护人', detail.maintainerName || '未记录'], ['发布版本', detail.version || '—'], ['调用次数', String(detail.callCount ?? '—')], ['下载次数', String(detail.downloadCount ?? '—')], ['状态', detail.status], ['描述', detail.description], ['执行指令', detail.instructions], ['挂载知识库', detail.knowledgeBases?.map(row => `${row.name}${row.version ? ` · ${row.version}` : ''}`).join('、') || '无'], ['资源使用说明', detail.resourceUsage || '未设置'], ['运行环境要求', detail.compatibility || '未设置'],
    ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd style={{ whiteSpace: 'pre-wrap' }}>{value}</dd></div>)}</dl><h3>Skill 定义</h3><pre className="markdown-preview">{detail.skillMarkdown || '发布定义缺失，请联系维护人'}</pre>{error && <p role="alert" className="error-banner">{error}</p>}</Dialog>}
    {classDetail && <Dialog title="技能大类详情" onClose={() => setClassDetail(null)} footer={<><button className="button" onClick={() => setClassDetail(null)}>关闭</button><button className="button primary" disabled={!classDetail.template} onClick={() => downloadBlob(new Blob([classDetail.template!], { type: 'text/plain;charset=utf-8' }), `${classDetail.name.replace(/[\\/<>:"|?*]/g, '_')}-Skill模板.md`)}>下载模板</button></>}><h3>{classDetail.name} · {classDetail.id}</h3><p>{classDetail.description || '暂无大类描述'}</p><dl className="constraint-details">{[['输入 Schema', classDetail.input_schema], ['输出 Schema', classDetail.output_schema]].map(([label, value]) => <div key={String(label)}><dt>{String(label)}</dt><dd><pre className="markdown-preview">{value ? JSON.stringify(value, null, 2) : '未配置'}</pre></dd></div>)}</dl><h3>Skill 模板</h3><pre className="markdown-preview">{classDetail.template || '未配置'}</pre></Dialog>}
    {debugItem && <DebugDialog key={`${debugItem.id}-${debugItem.buildId}`} item={debugItem} onClose={() => { setDebugItem(null); setReload(value => value + 1) }} onResult={debug => setDebugItem(previous => previous ? { ...previous, debug } : previous)} />}
  </>
}
