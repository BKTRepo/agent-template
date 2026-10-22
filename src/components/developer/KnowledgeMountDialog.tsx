import { useState } from 'react'
import Dialog from './Dialog'
import SearchSelect from './SearchSelect'
import { useDeveloperStore } from '@/stores/developerStore'
import { useAccessStore } from '@/stores/accessStore'
import { ALL_APPLICATIONS, applications, applicationText } from '@/lib/access'
import { skillClasses } from '@/mocks/developerData'
import { mountKnowledge } from '@/api/knowledgeMount'
import type { KnowledgeBase } from '@/types/developer'
const empty = { name: '', classId: '', app: '', maintainer: '' }
export default function KnowledgeMountDialog({ kb, onClose }: { kb: KnowledgeBase; onClose: () => void }) {
  const actor = useAccessStore(state => state.actor)
  const all = useDeveloperStore(state => state.implementations).filter(item => item.creatorId === actor.id)
  const [filters, setFilters] = useState(empty)
  const [applied, setApplied] = useState(empty)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [usage, setUsage] = useState(`执行时检索“${kb.name}”，用于${kb.description || '核对相关业务规则'}。`)
  const rows = all.filter(item => `${item.name} ${item.description} ${skillClasses.find(row => row.id === item.classId)?.name}`.toLowerCase().includes(applied.name.trim().toLowerCase()) && (!applied.classId || applied.classId === item.classId) && (!applied.app || item.applicationIds?.some(id => id === '*' || id === applied.app)) && (!applied.maintainer || item.creatorName === applied.maintainer))
  async function mount(ids: string[]) { setBusy(true); setError(''); try { const count = await mountKnowledge(kb.id, ids, usage); setNotice(`已挂载至 ${count} 个本人技能（本地模拟），版本已递增。`) } catch (error) { setError((error as Error).message) } finally { setBusy(false) } }
  return <Dialog wide title={`挂载知识库到技能 · ${kb.name}`} busy={busy} onClose={onClose} footer={<button className="button" disabled={busy} onClick={onClose}>关闭</button>}><p className="helper-text">选择本人创建的技能保存挂载关系。其他人的技能可在技能中心查看和测试。</p><form className="catalog-filters" onSubmit={event => { event.preventDefault(); setApplied(filters) }}><input aria-label="挂载目标名称模糊搜索" placeholder="名称或描述模糊搜索" value={filters.name} onChange={event => setFilters(old => ({ ...old, name: event.target.value }))} /><select aria-label="挂载目标技能大类" value={filters.classId} onChange={event => setFilters(old => ({ ...old, classId: event.target.value }))}><option value="">全部技能大类</option>{skillClasses.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select><SearchSelect label="挂载目标应用" value={filters.app} options={[{ id: ALL_APPLICATIONS, name: '全应用适用' }, ...applications]} onChange={app => setFilters(old => ({ ...old, app }))} placeholder="全部应用" /><SearchSelect label="挂载目标维护人" value={filters.maintainer} options={[{ id: actor.name, name: actor.name }]} onChange={maintainer => setFilters(old => ({ ...old, maintainer }))} placeholder="全部维护人" /><button className="button primary">搜索</button><button type="button" className="button" onClick={() => { setFilters(empty); setApplied(empty) }}>重置</button></form><label className="form-field"><span>资源使用说明</span><textarea maxLength={10000} value={usage} onChange={event => setUsage(event.target.value)} /><p className="helper-text">保留目标技能原说明，并追加本次知识库的使用说明。</p></label><button className="button" disabled={busy || !rows.some(row => !row.resourceIds.includes(kb.id))} onClick={() => void mount(rows.filter(row => !row.resourceIds.includes(kb.id)).map(row => row.id))}>挂载全部筛选结果</button><div className="assistant-skill-results">{rows.map(item => <article key={item.id}><div><h3>{item.name}</h3><p>{item.description}</p><small>{skillClasses.find(row => row.id === item.classId)?.name} · {applicationText(item)} · {item.version}</small></div><button className="button small" disabled={busy || item.resourceIds.includes(kb.id)} onClick={() => void mount([item.id])}>{item.resourceIds.includes(kb.id) ? '已挂载' : '挂载'}</button></article>)}{!rows.length && <p className="empty-table">未找到本人可挂载的技能。</p>}</div>{error && <p role="alert" className="error-banner">{error}</p>}{notice && <p role="status" className="form-hint">{notice}</p>}</Dialog>
}
