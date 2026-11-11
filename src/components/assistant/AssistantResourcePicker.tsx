import { useEffect, useState } from 'react'
import Dialog from '@/components/developer/Dialog'
import SearchSelect from '@/components/developer/SearchSelect'
import ListPagination from '@/components/common/ListPagination'
import { getCatalogMetadata, listCatalogSkills, type CatalogMetadata } from '@/api/skillCatalog'
import { listKnowledgeBasesPage } from '@/api/knowledge'
import type { Implementation, KnowledgeBase } from '@/types/developer'

export default function AssistantResourcePicker({ kind, selected, busy, onSkill, onKnowledge, onClose }: {
  kind: 'skills' | 'knowledge'; selected: string[]; busy: boolean
  onSkill: (item: Implementation) => Promise<void>; onKnowledge: (item: KnowledgeBase) => Promise<void>; onClose: () => void
}) {
  const initial = { name: '', classId: '', application: '', maintainer: '' }
  const [filters, setFilters] = useState(initial), [applied, setApplied] = useState(initial)
  const [metadata, setMetadata] = useState<CatalogMetadata>()
  const [page, setPage] = useState(1), [total, setTotal] = useState(0), [pages, setPages] = useState(1)
  const [skills, setSkills] = useState<Implementation[]>([]), [knowledge, setKnowledge] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(false), [adding, setAdding] = useState(false), [error, setError] = useState(''), [reload, setReload] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    void getCatalogMetadata(controller.signal).then(setMetadata).catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
    return () => controller.abort()
  }, [reload])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setSkills([]); setKnowledge([])
    void (async () => {
      const result = kind === 'skills'
        ? await listCatalogSkills({ ...applied, system: applied.application }, page, controller.signal, true)
        : await listKnowledgeBasesPage(page, applied.name, controller.signal, applied, true)
      if (controller.signal.aborted) return
      if (kind === 'skills') setSkills(result.items as Implementation[])
      else setKnowledge(result.items as KnowledgeBase[])
      setTotal(result.total); setPages(result.pages)
      const validPage = Math.min(result.page, result.pages)
      if (validPage !== page) setPage(validPage)
    })().catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [kind, applied, page, reload])
  const blocked = busy || loading || adding
  function search(reset = false) { setPage(1); setApplied(reset ? initial : { ...filters }); if (reset) setFilters(initial) }
  async function choose(item: Implementation | KnowledgeBase) {
    setAdding(true); setError('')
    try { if (kind === 'skills') await onSkill(item as Implementation); else await onKnowledge(item as KnowledgeBase) }
    catch (reason) { setError((reason as Error).message) } finally { setAdding(false) }
  }
  const applicationName = (ids: string[] = []) => ids.map(id => metadata?.applications.find(row => row.id === id)?.name || id).join('、') || '未关联应用'
  return <Dialog className="assistant-owned-dialog" wide title={kind === 'skills' ? '加载 Skill 到对话台' : '挂载知识库到对话台'} busy={adding} onClose={onClose}
    footer={<button className="button" disabled={adding} onClick={onClose}>完成</button>}>
    <form className="catalog-filters" onSubmit={event => { event.preventDefault(); search() }}>
      <input aria-label={kind === 'skills' ? '助手技能名称搜索' : '助手知识库名称搜索'} placeholder="名称模糊搜索" value={filters.name} onChange={event => setFilters({ ...filters, name: event.target.value })} />
      {kind === 'skills' && <SearchSelect label="助手技能类" value={filters.classId} options={metadata?.skill_classes.filter(row => row.is_enabled) ?? []} placeholder="全部技能类" onChange={classId => setFilters({ ...filters, classId })} />}
      <SearchSelect label="助手所属应用" value={filters.application} options={metadata?.applications ?? []} placeholder="全部应用" onChange={application => setFilters({ ...filters, application })} />
      {kind === 'skills' && <SearchSelect label="助手维护人" value={filters.maintainer} options={metadata?.maintainers ?? []} placeholder="全部维护人" onChange={maintainer => setFilters({ ...filters, maintainer })} />}
      <button className="button primary" disabled={blocked}>搜索</button><button type="button" className="button" disabled={blocked} onClick={() => search(true)}>重置</button>
    </form>
    {error && <p className="error-banner" role="alert">{error}<button className="button small" disabled={blocked} onClick={() => setReload(value => value + 1)}>重试</button></p>}
    {loading && <p role="status">正在加载…</p>}
    <div className="assistant-skill-results">{kind === 'skills' ? skills.map(item => <article key={item.id}><div><h3>{item.name}</h3><p>{item.description}</p>
      <div className="knowledge-selected"><span className="status-tag blue">{metadata?.skill_classes.find(row => row.id === item.classId)?.name}</span><span>{applicationName(item.applicationIds)}</span></div></div>
      <button className="button small" disabled={blocked || selected.includes(item.id)} onClick={() => void choose(item)}>{selected.includes(item.id) ? '已加载' : '加载'}</button></article>)
      : <table className="knowledge-picker-table"><thead><tr>{['知识库', '标签', '可见范围', '文档数', '操作'].map(label => <th key={label}>{label}</th>)}</tr></thead>
        <tbody>{knowledge.map(item => <tr key={item.id}><td>{item.name}</td><td>{item.tagName || item.tag}</td><td>{item.scope === 'public' ? '全体可见' : '仅本人可见'}</td><td>{item.files.length}</td>
          <td><button className="button small" disabled={blocked || selected.includes(item.id)} onClick={() => void choose(item)}>{selected.includes(item.id) ? '已挂载' : '挂载'}</button></td></tr>)}</tbody></table>}
      {!loading && !error && !(kind === 'skills' ? skills.length : knowledge.length) && <p className="empty-table">未找到可加载的{kind === 'skills' ? '已上线技能' : '已处理完成知识库'}。</p>}
    </div>
    <ListPagination label="助手资源分页" total={total} page={page} pages={pages} busy={blocked} onPageChange={setPage} />
  </Dialog>
}
