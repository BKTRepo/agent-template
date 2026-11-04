import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Download, Sparkles } from 'lucide-react'
import Dialog from '@/components/developer/Dialog'
import DebugDialog from '@/components/developer/DebugDialog'
import SearchSelect from '@/components/developer/SearchSelect'
import { downloadBlob } from '@/lib/resourceStorage'
import { getCatalogClass, getCatalogMetadata, getCatalogSkill, listCatalogSkills, downloadCatalogSkill, prepareCatalogTest } from '@/api/skillCatalog'
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
  const [rows, setRows] = useState<Implementation[]>([])
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [total, setTotal] = useState(0)
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
    setMetadata(emptyMetadata); setRows([]); setExpanded([]); setFilters(emptyFilters); setApplied(emptyFilters); setPage(1)
    return () => { generation.current++ }
  }, [token, actor])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setRows([]); setError('')
    void Promise.all([listCatalogSkills(applied, page, controller.signal), getCatalogMetadata(controller.signal)])
      .then(([result, next]) => {
        if (controller.signal.aborted) return
        setRows(result.items); setMetadata(next); setTotal(result.total); setPages(result.pages); setPage(result.page)
        setExpanded(previous => previous.length ? previous : next.skill_classes.map(row => row.id))
      }).catch(reason => { if (!controller.signal.aborted) { setMetadata(emptyMetadata); setTotal(0); setError((reason as Error).message) } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [applied, page, reload, token, actor])
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
        setRows(previous => previous.map(row => row.id === updated.id ? updated : row))
        setDetail(previous => previous?.id === updated.id ? updated : previous)
      }
    })
  }
  const classes = metadata.skill_classes.filter(row => (!applied.classId || row.id === applied.classId) &&
    (!applied.name && !applied.system && !applied.maintainer || rows.some(item => item.classId === row.id)))
  const allExpanded = classes.length > 0 && classes.every(row => expanded.includes(row.id))
  const applicationName = (item: Implementation) => (item.applicationIds ?? []).map(id => id === '*' ? '全应用适用' : metadata.applications.find(row => row.id === id)?.name || id).join('、') || '未关联应用'
  return <>
    <div className="page-heading"><div><h1>技能中心</h1><p>Skill 类 + 实现类管理 · 已上线可在线测试，已下线保留详情和下载</p></div><button className="button" disabled={loading} onClick={() => setReload(value => value + 1)}>刷新</button></div>
    <form className="surface catalog-filters" onSubmit={event => { event.preventDefault(); setApplied({ ...filters }); setPage(1) }}>
      <input aria-label="技能名称模糊搜索" placeholder="名称模糊搜索" value={filters.name} onChange={event => setFilters(previous => ({ ...previous, name: event.target.value }))} />
      <select aria-label="技能类" value={filters.classId} onChange={event => setFilters(previous => ({ ...previous, classId: event.target.value }))}><option value="">全部技能大类</option>{metadata.skill_classes.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
      <SearchSelect label="筛选所属应用" value={filters.system} options={metadata.applications.filter(row => row.id !== '*')} placeholder="全部应用" onChange={value => setFilters(previous => ({ ...previous, system: value }))} />
      <SearchSelect label="维护人" value={filters.maintainer} options={metadata.maintainers} placeholder="全部维护人" onChange={value => setFilters(previous => ({ ...previous, maintainer: value }))} />
      <button className="button primary" disabled={loading}>搜索</button><button type="button" className="button" disabled={loading} onClick={() => { setFilters(emptyFilters); setApplied({ ...emptyFilters }); setPage(1) }}>重置</button>
    </form>
    <button className="button" disabled={!classes.length || loading} onClick={() => setExpanded(allExpanded ? [] : classes.map(row => row.id))}>{allExpanded ? '收起所有技能' : '展开所有技能'}</button>
    {error && <p className="error-banner" role="alert">{error}<button className="button small" onClick={() => setReload(value => value + 1)}>重新加载</button></p>}
    {loading && <p className="helper-text" role="status">正在加载技能目录…</p>}
    {!loading && !error && total === 0 && <p className="helper-text" role="status">暂无符合条件的已发布实现类</p>}
    <div className="skill-group-list" aria-busy={loading}>{!loading && classes.map(skillClass => {
      const items = rows.filter(row => row.classId === skillClass.id)
      return <section className="surface skill-group" key={skillClass.id}><div className="skill-group-heading"><Sparkles size={22} /><div><h2><button className="skill-class-title" onClick={() => setExpanded(old => old.includes(skillClass.id) ? old.filter(id => id !== skillClass.id) : [...old, skillClass.id])}>{skillClass.name}</button> <small>{skillClass.id}</small></h2><p>{skillClass.description || '暂无大类描述'}</p></div><span className="status-tag neutral">本页 {items.length} 个实现</span><span className={`status-tag ${skillClass.is_enabled ? 'green' : 'neutral'}`}>{skillClass.is_enabled ? '已启用' : '已停用'}</span><button className="button small" disabled={!!busy} onClick={() => inspectClass(skillClass.id)}>类详情</button><button className="icon-button" aria-label={`${expanded.includes(skillClass.id) ? '收起' : '展开'} ${skillClass.name}`} onClick={() => setExpanded(previous => previous.includes(skillClass.id) ? previous.filter(id => id !== skillClass.id) : [...previous, skillClass.id])}><ChevronDown size={18} /></button></div>
        {expanded.includes(skillClass.id) && <div className="implementation-table-wrap"><table className="implementation-table"><thead><tr>{['实现名称', '所属应用', '维护人', '版本', '调用次数', '状态', '操作'].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{items.map(item => <tr key={item.id}><td className="implementation-name">{item.name}</td><td>{applicationName(item)}</td><td>{item.maintainerName}</td><td>{item.version || '—'}</td><td>{item.callCount ?? '—'}</td><td><span className={`status-tag ${item.status === '已上线' ? 'green' : 'neutral'}`}>{item.status}</span></td><td><div className="table-actions"><button className="button small" disabled={!!busy} onClick={() => inspect(item)}>详情</button><button className="button small" disabled={!!busy || item.status !== '已上线' || !skillClass.is_enabled || !item.buildId} onClick={() => inspect(item, true)}>在线测试</button><button className="button small" disabled={!!busy || !item.buildId} onClick={() => download(item)}><Download size={13} />{busy === item.id ? '处理中…' : '下载技能'}</button></div></td></tr>)}{!items.length && <tr><td className="empty-table" colSpan={7}>本页暂无该大类的实现类</td></tr>}</tbody></table></div>}
      </section>
    })}</div>
    <div className="developer-pagination" aria-label="技能目录分页"><span>共 {total} 条 · 第 {page} / {pages} 页</span><button className="button small" disabled={loading || page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button><button className="button small" disabled={loading || page >= pages} onClick={() => setPage(value => value + 1)}>下一页</button></div>
    {detail && <Dialog wide title={`实现类详情 · ${detail.name}`} onClose={() => setDetail(null)} footer={<><button className="button" onClick={() => setDetail(null)}>关闭</button><button className="button primary" disabled={!!busy || !detail.buildId} onClick={() => download(detail)}>下载技能 ZIP</button></>}><dl className="constraint-details">{[
      ['所属技能大类', metadata.skill_classes.find(row => row.id === detail.classId)?.name || detail.classId], ['所属应用', applicationName(detail)], ['维护人', detail.maintainerName || '未记录'], ['发布版本', detail.version || '—'], ['调用次数', String(detail.callCount ?? '—')], ['下载次数', String(detail.downloadCount ?? '—')], ['状态', detail.status], ['描述', detail.description], ['执行指令', detail.instructions], ['挂载知识库', detail.knowledgeBases?.map(row => row.name).join('、') || '无'], ['资源使用说明', detail.resourceUsage || '未设置'], ['运行环境要求', detail.compatibility || '未设置'],
    ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd style={{ whiteSpace: 'pre-wrap' }}>{value}</dd></div>)}</dl><h3>Skill 定义</h3><pre className="markdown-preview">{detail.skillMarkdown || '发布定义缺失，请联系维护人'}</pre>{error && <p role="alert" className="error-banner">{error}</p>}</Dialog>}
    {classDetail && <Dialog title="技能大类详情" onClose={() => setClassDetail(null)} footer={<><button className="button" onClick={() => setClassDetail(null)}>关闭</button><button className="button primary" disabled={!classDetail.template} onClick={() => downloadBlob(new Blob([classDetail.template!], { type: 'text/plain;charset=utf-8' }), `${classDetail.name.replace(/[\\/<>:"|?*]/g, '_')}-Skill模板.md`)}>下载模板</button></>}><h3>{classDetail.name} · {classDetail.id}</h3><p>{classDetail.description || '暂无大类描述'}</p><dl className="constraint-details">{[['输入 Schema', classDetail.input_schema], ['输出 Schema', classDetail.output_schema]].map(([label, value]) => <div key={String(label)}><dt>{String(label)}</dt><dd><pre className="markdown-preview">{value ? JSON.stringify(value, null, 2) : '未配置'}</pre></dd></div>)}</dl><h3>Skill 模板</h3><pre className="markdown-preview">{classDetail.template || '未配置'}</pre></Dialog>}
    {debugItem && <DebugDialog key={`${debugItem.id}-${debugItem.buildId}`} item={debugItem} onClose={() => { setDebugItem(null); setReload(value => value + 1) }} onResult={debug => setDebugItem(previous => previous ? { ...previous, debug } : previous)} />}
  </>
}
