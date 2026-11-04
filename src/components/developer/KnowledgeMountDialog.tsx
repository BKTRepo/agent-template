import { useEffect, useState } from 'react'
import Dialog from './Dialog'
import SearchSelect from './SearchSelect'
import { useAccessStore } from '@/stores/accessStore'
import { applicationText } from '@/lib/access'
import { loadOwnedMountTargets, mountKnowledge, type KnowledgeMountResult } from '@/api/knowledgeMount'
import { getDeveloperMetadata, type DeveloperMetadata } from '@/api/developerCenter'
import type { Implementation, KnowledgeBase } from '@/types/developer'

const empty = { name: '', classId: '', app: '', maintainer: '' }
export default function KnowledgeMountDialog({ kb, onClose }: { kb: KnowledgeBase; onClose: () => void }) {
  const actor = useAccessStore(state => state.actor)
  const [targets, setTargets] = useState<Implementation[]>([])
  const [metadata, setMetadata] = useState<DeveloperMetadata>({ skill_classes: [], applications: [] })
  const [filters, setFilters] = useState(empty), [applied, setApplied] = useState(empty)
  const [selected, setSelected] = useState<string[]>([])
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [result, setResult] = useState<KnowledgeMountResult>()
  useEffect(() => {
    let active = true
    void Promise.all([loadOwnedMountTargets(), getDeveloperMetadata()]).then(([items, options]) => {
      if (active) { setTargets(items); setMetadata(options) }
    }).catch(reason => { if (active) setError(reason.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [actor.id])
  const groups = metadata.skill_classes.map(kind => ({ ...kind, id: String(kind.id),
    items: targets.filter(item => String(item.classId) === String(kind.id)) }))
  const shown = groups.filter(group => (!applied.classId || group.id === applied.classId)
    && (!applied.name || `${group.name} ${group.items.map(item => `${item.name} ${item.description}`).join(' ')}`.toLowerCase().includes(applied.name.trim().toLowerCase()))
    && (!applied.app || group.items.some(item => item.applicationIds?.some(id => id === '*' || id === applied.app)))
    && (!applied.maintainer || applied.maintainer === actor.name))
  const matched = groups.filter(group => selected.includes(group.id)).reduce((count, group) => count + group.items.length, 0)
  async function submit() {
    setBusy(true); setError(''); setResult(undefined)
    try {
      const reply = await mountKnowledge(kb.id, selected); setResult(reply)
      setTargets(await loadOwnedMountTargets())
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  return <Dialog wide title={`挂载知识库到技能 · ${kb.name}`} busy={busy} onClose={onClose} footer={<>
    <button className="button" disabled={busy} onClick={onClose}>关闭</button>
    <button className="button primary" disabled={busy || loading || !matched} onClick={() => void submit()}>{busy ? '正在保存…' : '确认挂载'}</button>
  </>}>
    <p className="helper-text">多选抽象类，将知识库挂载到这些类下本人创建的全部实现。搜索仅定位抽象类，不缩小该类的本人实现范围。按当前技能更新规则，保存后生成新版本并转为草稿，需重新构建、调试和发布。</p>
    <form className="catalog-filters" onSubmit={event => { event.preventDefault(); setApplied(filters) }}>
      <input aria-label="挂载目标名称模糊搜索" placeholder="名称或描述模糊搜索" value={filters.name} onChange={event => setFilters(old => ({ ...old, name: event.target.value }))} />
      <select aria-label="挂载目标技能大类" value={filters.classId} onChange={event => setFilters(old => ({ ...old, classId: event.target.value }))}><option value="">全部抽象类</option>{metadata.skill_classes.map(kind => <option key={kind.id} value={kind.id}>{kind.name}</option>)}</select>
      <SearchSelect label="挂载目标应用" value={filters.app} options={metadata.applications} onChange={app => setFilters(old => ({ ...old, app }))} placeholder="全部应用" />
      <SearchSelect label="挂载目标维护人" value={filters.maintainer} options={[{ id: actor.name, name: actor.name }]} onChange={maintainer => setFilters(old => ({ ...old, maintainer }))} placeholder="全部维护人" />
      <button className="button primary">搜索</button><button type="button" className="button" onClick={() => { setFilters(empty); setApplied(empty) }}>重置</button>
    </form>
    <p role="status">已选 {selected.length} 个抽象类，共 {matched} 个本人实现（含当前搜索结果外的已选类）。</p>
    {loading ? <p role="status">正在查询全部本人实现…</p> : <div className="assistant-skill-results">{shown.map(group => {
      const existing = group.items.filter(item => item.resourceIds.includes(kb.id)).length
      return <article key={group.id}><label className="inline-choice"><input type="checkbox" aria-label={`选择抽象类 ${group.name}`} checked={selected.includes(group.id)} disabled={busy || !group.items.length} onChange={event => setSelected(old => event.target.checked ? [...old, group.id] : old.filter(id => id !== group.id))} /><div><h3>{group.name}</h3><p>本人实现 {group.items.length} 个 · 已挂载 {existing} 个 · 待挂载 {group.items.length - existing} 个</p><small>{group.items.map(item => `${item.name}（${applicationText(item)}）`).join('、') || '该类下暂无本人实现'}</small></div></label></article>
    })}{!shown.length && <p className="empty-table">没有匹配的抽象类。</p>}</div>}
    {result && <div role="status"><p>命中 {result.matched} 个：已保存 {result.saved} 个，已存在 {result.skipped} 个，失败 {result.failures.length} 个。需要重新构建、调试并发布的技能请到开发者中心继续处理。</p>{result.failures.map(item => <p className="field-error" key={item.id}>{item.name}：{item.message}</p>)}{!!result.failures.length && <p>可再次确认挂载，仅重试尚未保存的实现；已成功的不会重复生成版本。</p>}</div>}
    {error && <p role="alert" className="error-banner">{error}</p>}
  </Dialog>
}
