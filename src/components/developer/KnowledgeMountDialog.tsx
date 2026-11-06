import { useEffect, useRef, useState } from 'react'
import Dialog from './Dialog'
import SearchSelect from './SearchSelect'
import ImplementationSummaryCells, { implementationSummaryHeaders } from './ImplementationSummaryCells'
import ListPagination from '@/components/common/ListPagination'
import { useAccessStore } from '@/stores/accessStore'
import { loadOwnedMountTargets, mountKnowledge, type KnowledgeMountResult } from '@/api/knowledgeMount'
import { getDeveloperMetadata, type DeveloperMetadata } from '@/api/developerCenter'
import type { Implementation, KnowledgeBase } from '@/types/developer'

const empty = { name: '', classId: '', app: '' }
export default function KnowledgeMountDialog({ kb, onClose }: { kb: KnowledgeBase; onClose: () => void }) {
  const actor = useAccessStore(state => state.actor)
  const [targets, setTargets] = useState<Implementation[]>([])
  const [metadata, setMetadata] = useState<DeveloperMetadata>({ skill_classes: [], applications: [] })
  const [filters, setFilters] = useState(empty), [applied, setApplied] = useState(empty)
  const [selected, setSelected] = useState<string[]>([]), [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [result, setResult] = useState<KnowledgeMountResult>()
  const selectPage = useRef<HTMLInputElement>(null)
  useEffect(() => {
    let active = true
    setLoading(true); setSelected([]); setPage(1); setError(''); setResult(undefined)
    void Promise.all([loadOwnedMountTargets(), getDeveloperMetadata()]).then(([items, options]) => {
      if (active) { setTargets(items); setMetadata(options) }
    }).catch(reason => { if (active) setError(reason.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [actor.id])
  const classes = [...metadata.skill_classes, ...[...new Set(targets.map(item => item.classId))]
    .filter(id => !metadata.skill_classes.some(kind => kind.id === id)).map(id => ({ id, name: `技能类 ${id}` }))]
  const shown = targets.filter(item => (!applied.classId || item.classId === applied.classId)
    && (!applied.name.trim() || `${item.name} ${item.description}`.toLocaleLowerCase().includes(applied.name.trim().toLocaleLowerCase()))
    && (!applied.app || item.applicationIds?.some(id => id === '*' || id === applied.app)))
  const pages = Math.max(1, Math.ceil(shown.length / 10)), currentPage = Math.min(page, pages)
  const rows = shown.slice((currentPage - 1) * 10, currentPage * 10)
  const selectedSet = new Set(selected), allPageSelected = rows.length > 0 && rows.every(item => selectedSet.has(item.id))
  useEffect(() => { if (selectPage.current) selectPage.current.indeterminate = !allPageSelected && rows.some(item => selectedSet.has(item.id)) }, [allPageSelected, rows, selected])
  function togglePage(checked: boolean) {
    setSelected(previous => checked ? [...new Set([...previous, ...rows.map(item => item.id)])] : previous.filter(id => !rows.some(item => item.id === id)))
  }
  async function submit() {
    if (busy || loading || !selected.length) return
    setBusy(true); setError(''); setResult(undefined)
    try {
      const reply = await mountKnowledge(kb.id, selected); setResult(reply)
      try { setTargets(await loadOwnedMountTargets()) }
      catch (reason) { setError(`挂载操作已完成，技能列表刷新失败：${(reason as Error).message}`) }
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  return <Dialog wide title={`挂载知识库到技能 · ${kb.name}`} busy={busy} onClose={onClose} footer={<>
    <button className="button" disabled={busy} onClick={onClose}>关闭</button>
    <button className="button primary" disabled={busy || loading || !selected.length} onClick={() => void submit()}>{busy ? '正在保存…' : '确认挂载'}</button>
  </>}>
    <p className="helper-text">展示本人创建的所有状态技能，仅挂载勾选的实现。保存后转为草稿，需重新构建、调试并发布。</p>
    <form className="catalog-filters mount-filters" onSubmit={event => { event.preventDefault(); setApplied(filters); setPage(1) }}>
      <input aria-label="挂载目标名称模糊搜索" placeholder="名称或描述模糊搜索" value={filters.name} disabled={busy} onChange={event => setFilters(old => ({ ...old, name: event.target.value }))} />
      <select aria-label="挂载目标技能类" value={filters.classId} disabled={busy} onChange={event => setFilters(old => ({ ...old, classId: event.target.value }))}><option value="">全部技能类</option>{classes.map(kind => <option key={kind.id} value={kind.id}>{kind.name}</option>)}</select>
      <SearchSelect label="挂载目标应用" value={filters.app} options={metadata.applications} disabled={busy} onChange={app => setFilters(old => ({ ...old, app }))} placeholder="全部应用" />
      <label className="mount-maintainer"><span>维护人 <em>*</em></span><input aria-label="挂载目标维护人" value={actor.name || actor.id} disabled readOnly /></label>
      <button className="button primary" disabled={busy || loading}>搜索</button><button type="button" className="button" disabled={busy} onClick={() => { setFilters(empty); setApplied(empty); setPage(1) }}>重置</button>
    </form>
    <p role="status">已选 {selected.length} 个技能实现。</p>
    {loading ? <p role="status">正在查询本人技能…</p> : <>
      <div className="implementation-table-wrap"><table className="implementation-table mount-implementation-table"><thead><tr>
        <th scope="col"><input ref={selectPage} type="checkbox" aria-label="选择当前页全部技能" checked={allPageSelected} disabled={busy || !rows.length} onChange={event => togglePage(event.target.checked)} /></th>
        {implementationSummaryHeaders.map(label => <th key={label} scope="col">{label}</th>)}
      </tr></thead><tbody>{rows.map(item => <tr key={item.id}>
        <td><input type="checkbox" aria-label={`选择技能 ${item.name}`} checked={selectedSet.has(item.id)} disabled={busy} onChange={event => setSelected(previous => event.target.checked ? [...new Set([...previous, item.id])] : previous.filter(id => id !== item.id))} /></td>
        <ImplementationSummaryCells item={item} skillClasses={classes} />
      </tr>)}{!rows.length && <tr><td colSpan={6} className="empty-table">暂无符合条件的本人技能。</td></tr>}</tbody></table></div>
      <ListPagination total={shown.length} page={currentPage} pages={pages} label="挂载技能列表分页" busy={busy} onPageChange={setPage} />
    </>}
    {result && <div role="status"><p>命中 {result.matched} 个：已保存 {result.saved} 个，已存在 {result.skipped} 个，失败 {result.failures.length} 个。</p>{result.failures.map(item => <p className="platform-field-error" key={item.id}>{item.name}：{item.message}</p>)}{!!result.failures.length && <p>可再次确认挂载，仅重试尚未保存的实现。</p>}{result.refreshWarning && <p className="platform-field-error">{result.refreshWarning}</p>}</div>}
    {error && <p role="alert" className="error-banner">{error}</p>}
  </Dialog>
}
