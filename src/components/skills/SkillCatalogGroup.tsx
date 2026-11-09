import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Download, Sparkles } from 'lucide-react'
import NameDescription, { DescriptionPreview } from '@/components/common/NameDescription'
import ListPagination from '@/components/common/ListPagination'
import { listCatalogSkills, type CatalogClass, type CatalogFilters } from '@/api/skillCatalog'
import type { Implementation } from '@/types/developer'

export default function SkillCatalogGroup({ skillClass, filters, expanded, onToggle, reload, busy, applicationName, onInspect, onInspectClass, onDownload, onTotal }: {
  skillClass: CatalogClass; filters: CatalogFilters; expanded: boolean; onToggle: () => void; reload: number; busy?: string
  applicationName: (item: Implementation) => string
  onInspect: (item: Implementation, test?: boolean) => Promise<void>; onInspectClass: (id: string) => Promise<void>
  onDownload: (item: Implementation) => Promise<void>; onTotal: (id: string, total: number) => void
}) {
  const [page, setPage] = useState(1)
  const [result, setResult] = useState({ items: [] as Implementation[], total: 0, pages: 1, page: 1 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError('')
    void listCatalogSkills({ ...filters, classId: skillClass.id }, page, controller.signal).then(next => {
      if (controller.signal.aborted) return
      setResult(next); setPage(next.page); onTotal(skillClass.id, next.total)
    }).catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [filters, skillClass.id, page, reload, retry, onTotal])
  const filtering = !!(filters.name || filters.system || filters.maintainer)
  if (filtering && !loading && !error && result.total === 0) return null
  return <section className="surface skill-group" aria-label={skillClass.name}>
    <div className="skill-group-heading"><Sparkles size={22} /><div><h2><button className="skill-class-title" aria-expanded={expanded} onClick={onToggle}>{skillClass.name}</button></h2><DescriptionPreview description={skillClass.description} /></div>
      <span className="status-tag neutral">{result.total} 个实现</span><span className={`status-tag ${skillClass.is_enabled ? 'green' : 'neutral'}`}>{skillClass.is_enabled ? '已启用' : '已停用'}</span>
      <button className="button small" disabled={!!busy} onClick={() => onInspectClass(skillClass.id)}>类详情</button>
      <button className="icon-button" aria-expanded={expanded} aria-label={`${expanded ? '收起' : '展开'} ${skillClass.name}`} onClick={onToggle}>{expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}</button>
    </div>
    {expanded && <>
      {error && <p className="error-banner" role="alert">{error}<button className="button small" onClick={() => setRetry(value => value + 1)}>重新加载</button></p>}
      <div className="implementation-table-wrap" aria-busy={loading}><table className="implementation-table"><thead><tr>{['实现名称', '所属应用', '维护人', '版本', '调用次数', '状态', '操作'].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>
        {!loading && !error && result.items.map(item => <tr key={item.id}><td className="implementation-name"><NameDescription name={item.name} description={item.description} /></td><td>{applicationName(item)}</td><td>{item.maintainerName}</td><td>{item.version || '—'}</td><td>{item.callCount ?? '—'}</td><td><span className={`status-tag ${item.status === '已上线' ? 'green' : 'neutral'}`}>{item.status}</span></td><td><div className="table-actions"><button className="button small" disabled={!!busy} onClick={() => onInspect(item)}>详情</button><button className="button small" disabled={!!busy || item.status !== '已上线' || !skillClass.is_enabled || !item.buildId} onClick={() => onInspect(item, true)}>在线测试</button><button type="button" className="button small skill-download-button" title="下载技能" aria-label={busy === item.id ? '处理中…' : '下载技能'} aria-busy={busy === item.id} disabled={!!busy || !item.buildId} onClick={() => onDownload(item)}><Download size={16} aria-hidden="true" /></button></div></td></tr>)}
        {(loading || error || !result.items.length) && <tr><td className="empty-table" colSpan={7}>{loading ? '正在加载实现列表…' : error ? '实现列表加载失败，请重试' : '暂无该技能类的已发布实现'}</td></tr>}
      </tbody></table></div>
      <ListPagination total={result.total} page={result.page} pages={result.pages} label={`${skillClass.name}实现列表分页`} busy={loading || !!error} onPageChange={setPage} />
    </>}
  </section>
}
