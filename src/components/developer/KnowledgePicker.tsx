import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { listKnowledgeOptionsPage } from '@/api/knowledge'
import { applicationText } from '@/lib/access'
import { knowledgeIdentity, uniqueKnowledgeSelections } from '@/lib/knowledgeSelection'
import { useAuthStore } from '@/stores/authStore'
import type { KnowledgeBaseOption, KnowledgeSelection } from '@/types/developer'

interface PageRequest { controller: AbortController; search: string; offset: number; hasMore: boolean; busy: boolean }

export default function KnowledgePicker({ selected, onChange, disabled }: { selected: KnowledgeSelection[]; onChange: (items: KnowledgeSelection[]) => void; disabled: boolean }) {
  const labelId = useId()
  const token = useAuthStore(state => state.session?.token)
  const [query, setQuery] = useState('')
  const [applied, setApplied] = useState({ search: '' })
  const [items, setItems] = useState<KnowledgeBaseOption[]>([])
  const [hasMore, setHasMore] = useState(true)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const request = useRef<PageRequest | undefined>(undefined)
  const list = useRef<HTMLDivElement>(null)
  const chosen = uniqueKnowledgeSelections(selected)
  const loadMore = useCallback(async () => {
    const current = request.current
    if (!current || current.busy || !current.hasMore || current.controller.signal.aborted) return
    current.busy = true; setLoading(true); setError('')
    const valid = () => request.current === current && !current.controller.signal.aborted
    try {
      const page = await listKnowledgeOptionsPage(current.search, current.offset, current.controller.signal)
      if (!valid()) return
      current.offset = page.nextOffset; current.hasMore = page.hasMore
      setItems(previous => uniqueKnowledgeSelections([...previous, ...page.items])); setHasMore(page.hasMore)
    } catch (reason) { if (valid()) setError((reason as Error).message) }
    finally { current.busy = false; if (valid()) setLoading(false) }
  }, [])
  useEffect(() => {
    const current: PageRequest = { controller: new AbortController(), search: applied.search, offset: 0, hasMore: true, busy: false }
    request.current = current
    setItems([]); setHasMore(true); setError('')
    if (list.current) list.current.scrollTop = 0
    void loadMore()
    return () => current.controller.abort()
  }, [applied, token, loadMore])
  useEffect(() => {
    // Skip non-completed source rows without leaving an empty, unscrollable list.
    const node = list.current
    if (!loading && !error && hasMore && node && node.scrollHeight <= node.clientHeight + 1) void loadMore()
  }, [items, loading, error, hasMore, loadMore])
  function search(value = query) { setApplied({ search: value.trim() }) }
  function select(item: KnowledgeBaseOption, checked: boolean) {
    onChange(checked ? uniqueKnowledgeSelections([...chosen, { id: item.id, name: item.name, version: item.version, source: item.source }])
      : chosen.filter(row => knowledgeIdentity(row.id) !== item.id))
  }
  return <section className="form-field knowledge-picker" aria-labelledby={labelId}>
    <span id={labelId}>挂载知识库</span>
    <div className="knowledge-search"><div className="knowledge-search-input"><Search size={16} aria-hidden="true" /><input aria-label="知识库名称模糊搜索" placeholder="知识库名称模糊搜索" value={query} disabled={disabled} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); search() } }} /></div><button type="button" className="button primary" disabled={disabled} onClick={() => search()}>搜索</button><button type="button" className="button" disabled={disabled} onClick={() => { setQuery(''); search('') }}>重置</button></div>
    <div className="knowledge-picker-frame">
      <div ref={list} className="knowledge-picker-scroll" role="region" aria-label="已处理完成的知识库列表，可上下滚动" tabIndex={0} aria-busy={loading} onScroll={event => { const node = event.currentTarget; if (!error && node.scrollHeight - node.scrollTop - node.clientHeight < 64) void loadMore() }}>
        <table className="knowledge-picker-table"><colgroup><col className="knowledge-choice-col" /><col className="knowledge-name-col" /><col className="knowledge-count-col" /><col className="knowledge-version-col" /><col className="knowledge-app-col" /><col /></colgroup>
          <thead><tr><th aria-label="选择" />{['知识库', '文件数', '版本', '所属应用', '维护人'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{items.map(item => <tr key={item.id} className={chosen.some(row => row.id === item.id) ? 'is-selected' : ''}>
            <td><input id={`${labelId}-${item.id}`} type="checkbox" aria-label={`选择 ${item.name}`} disabled={disabled} checked={chosen.some(row => row.id === item.id)} onChange={event => select(item, event.target.checked)} /></td>
            <td><label className="knowledge-picker-name" htmlFor={`${labelId}-${item.id}`}>{item.name}</label></td>
            <td>{item.fileCount}</td><td>{item.version || '—'}</td><td>{applicationText(item)}</td><td>{item.maintainer}</td>
          </tr>)}{!items.length && !loading && !error && <tr><td colSpan={6} className="knowledge-picker-empty">{applied.search ? '未找到匹配的已完成知识库' : '暂无已处理完成的可用知识库'}</td></tr>}</tbody>
        </table>
        {loading && <p className="knowledge-picker-feedback" role="status">{items.length ? '正在加载更多知识库…' : '正在加载知识库…'}</p>}
        {error && <div className="knowledge-picker-feedback error-banner" role="alert">{error}<button type="button" className="button small" disabled={disabled || loading} onClick={() => void loadMore()}>重试</button></div>}
      </div>
      <p className="knowledge-picker-total" aria-live="polite">{hasMore ? `已加载 ${items.length} 个知识库` : `${applied.search ? '搜索结果：' : '共 '}${items.length} 个知识库`}</p>
    </div>
    <div className="knowledge-picker-selected" aria-label="已选知识库"><p aria-live="polite">已选择 {chosen.length} 个知识库</p><div className="knowledge-selected">{chosen.map(item => <span className="knowledge-chip" key={item.id} title={`知识库编号：${item.id}`}>{item.name}<button type="button" className="icon-button" aria-label={`取消挂载 ${item.name}`} disabled={disabled} onClick={() => onChange(chosen.filter(row => knowledgeIdentity(row.id) !== item.id))}><X size={13} /></button></span>)}{!chosen.length && <span className="helper-text">暂无已选知识库</span>}</div></div>
  </section>
}
