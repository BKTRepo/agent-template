import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { searchKnowledgeBases } from '@/api/knowledge'
import { useKnowledgeStore } from '@/stores/knowledgeStore'
import { useAccessStore } from '@/stores/accessStore'
import { skillBackendEnabled } from '@/api/skillSession'
import type { KnowledgeBaseOption, KnowledgeSelection } from '@/types/developer'

export default function KnowledgePicker({ team, selected, onChange, disabled }: { team: string; selected: KnowledgeSelection[]; onChange: (items: KnowledgeSelection[]) => void; disabled: boolean }) {
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<KnowledgeBaseOption[]>([])
  const [demo, setDemo] = useState(false)
  const [loading, setLoading] = useState(true)
  const localKnowledge = useKnowledgeStore(state => state.knowledgeBases)
  const actor = useAccessStore(state => state.actor)
  useEffect(() => {
    if (!query.trim()) { setItems([]); setLoading(false); return }
    const controller = new AbortController()
    setLoading(true)
    const timer = window.setTimeout(() => {
      searchKnowledgeBases(query, team, controller.signal, true).then(result => {
        if (!controller.signal.aborted) { setItems(result.items); setDemo(result.demo); setLoading(false) }
      }).catch(() => { if (!controller.signal.aborted) setLoading(false) })
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [query, team, localKnowledge, actor])
  return <section className="form-field knowledge-picker" aria-labelledby="knowledge-label">
    <span id="knowledge-label">挂载知识库</span>
    <div className="knowledge-search"><input aria-label="知识库名称模糊搜索" placeholder="知识库名称模糊搜索" value={query} disabled={disabled} onChange={event => setQuery(event.target.value)} /><button type="button" className="button" disabled={disabled || !query} onClick={() => setQuery('')}>重置</button></div>
    <div className="knowledge-options" aria-busy={loading}>
      {!query.trim() ? <p className="helper-text">输入关键词搜索知识库后展示可挂载项</p> : loading ? <p className="helper-text">正在搜索知识库…</p> : items.length ? items.map(item => <label className="knowledge-option" key={item.id}>
        <input type="checkbox" disabled={disabled} checked={selected.some(row => row.id === item.id)} onChange={event => onChange(event.target.checked ? [...selected.filter(row => row.id !== item.id), { id: item.id, name: item.name, source: item.source }] : selected.filter(row => row.id !== item.id))} />
        <div><b>{item.name}</b><p>{item.description || '暂无知识库说明'}</p></div><span>{item.scope}</span>
      </label>) : <p className="helper-text">未找到匹配的知识库</p>}
    </div>
    {!!selected.length && <div className="knowledge-selected" aria-label="已选知识库"><span>已选 {selected.length} 项</span>{selected.map(item => <span className="knowledge-chip" key={item.id}>{item.name}<button type="button" className="icon-button" aria-label={`取消挂载 ${item.name}`} disabled={disabled} onClick={() => onChange(selected.filter(row => row.id !== item.id))}><X size={13} /></button></span>)}</div>}
    {demo && <p className="helper-text">{skillBackendEnabled ? '当前搜索结果为示例知识库。真实生成请取消示例挂载，使用“资源上传”添加真实文件。' : '当前知识库为示例数据，选择后使用模拟生成和调试；连接知识库接口后使用真实资源。'}</p>}
  </section>
}
