import { useEffect, useRef, useState } from 'react'
import { Bot, LoaderCircle, Paperclip, Plus, Send, X } from 'lucide-react'
import Dialog from '@/components/developer/Dialog'
import SearchSelect from '@/components/developer/SearchSelect'
import { skillContract } from '@/lib/skillContract'
import { createAssistantRequest, replyWithDemo, type AssistantMessage } from '@/api/assistant'
import { skillCatalog } from '@/lib/skillCatalog'
import { applications, applicationText } from '@/lib/access'
import { validateResourceFiles, resourceExtensions } from '@/lib/skillForm'
import { skillClasses } from '@/mocks/developerData'
import { useDeveloperStore } from '@/stores/developerStore'

export default function FloatingAssistant() {
  const implementations = useDeveloperStore(state => state.implementations)
  const catalog = skillCatalog(implementations, true).filter(row => skillClasses.find(kind => kind.id === row.classId)?.enabled !== false)
  const [open, setOpen] = useState(false)
  const [picking, setPicking] = useState(false)
  const [skillIds, setSkillIds] = useState<string[]>([])
  const [messages, setMessages] = useState<AssistantMessage[]>([])
  const [files, setFiles] = useState<File[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [filters, setFilters] = useState({ name: '', classId: '', application: '', maintainer: '' })
  const [applied, setApplied] = useState({ name: '', classId: '', application: '', maintainer: '' })
  const controller = useRef<AbortController | null>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const skills = catalog.filter(row => skillIds.includes(row.id))
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => { if (open) bottom.current?.scrollIntoView({ block: 'nearest' }) }, [open, messages, busy])
  function close() { setOpen(false); trigger.current?.focus() }
  function clear() { controller.current?.abort(); controller.current = null; setMessages([]); setError(''); setBusy(false) }
  function addFiles(incoming: File[]) {
    const existing = files.map((file, index) => ({ id: String(index), name: file.name, size: file.size, lastModified: file.lastModified }))
    const result = validateResourceFiles(incoming, existing)
    setFiles(previous => [...previous, ...result.accepted]); setError(result.errors.join('；'))
  }
  async function send() {
    if (busy) return
    let request
    try { request = createAssistantRequest(messages, text, files, skills.map(skillContract)) } catch (error) { setError((error as Error).message); return }
    const active = new AbortController()
    controller.current = active
    setMessages(previous => [...previous, { id: crypto.randomUUID(), role: 'user', text: request.messages.at(-1)!.text, attachments: request.files.map(file => file.name), skills: request.skills }])
    setFiles([]); setText(''); setError(''); setBusy(true)
    try {
      const response = await replyWithDemo(request, active.signal)
      if (!active.signal.aborted) setMessages(previous => [...previous, { id: crypto.randomUUID(), role: 'assistant', text: response }])
    } catch (error) { if (!active.signal.aborted) setError((error as Error).message) }
    finally { if (controller.current === active) { controller.current = null; setBusy(false) } }
  }
  const results = catalog.filter(row => row.name.toLowerCase().includes(applied.name.trim().toLowerCase()) && (!applied.classId || row.classId === applied.classId) && (!applied.application || (row.applicationIds ?? [row.system]).some(id => id === '*' || id === applied.application)) && (!applied.maintainer || row.creatorName === applied.maintainer))
  return <>
    <button ref={trigger} className="assistant-trigger" aria-label={open ? '收起智能助手' : '打开智能助手'} aria-expanded={open} onClick={() => open ? close() : setOpen(true)}><Bot size={25} /></button>
    {open && <aside className="assistant-panel" role="dialog" aria-label="AI 助手" aria-modal="false" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); close() } }}>
      <header className="assistant-header"><Bot size={20} /><h2>AI 助手</h2><button className="button small" onClick={clear}>清空聊天</button><button className="icon-button" aria-label="收起助手" onClick={close}><X size={18} /></button></header>
      <div className="assistant-skills"><div className="field-heading"><span>已加载 Skill</span><button className="button small" onClick={() => setPicking(true)}><Plus size={13} />加载 Skill</button></div><div className="knowledge-selected">{skills.map(skill => { const contract = skillContract(skill); return <article className="assistant-loaded-skill" key={skill.id}><div className="field-heading"><b>{skill.name}</b><button className="icon-button" disabled={busy} aria-label={`卸载 ${skill.name}`} onClick={() => setSkillIds(previous => previous.filter(id => id !== skill.id))}><X size={12} /></button></div><p>{skill.description}</p><dl><dt>输入</dt><dd>{contract.input}</dd><dt>输出</dt><dd>{contract.output}</dd></dl></article> })}{!skills.length && <span className="helper-text">尚未加载，可从全量已上线技能中选择。</span>}</div></div>
      <p className="assistant-notice">前端演示 · 对话历史不保存 · 文件每次手动上传</p>
      <div className="assistant-messages" role="log" aria-label="本次对话" aria-live="polite"><div className="assistant-message assistant">你好，我是 AI 测试助手。加载 Skill 后输入需求，或手动上传本次文件，即可开始演示对话。</div>{messages.map(message => <div className={`assistant-message ${message.role === 'user' ? 'user' : 'assistant'}`} key={message.id}><small>{message.role === 'user' ? '你' : 'AI 助手 · 模拟'}</small><p>{message.text}</p>{!!message.skills?.length && <details><summary>本轮已加载 Skill</summary>{message.skills.map(skill => <div key={skill.id}><b>{skill.name}</b><p>{skill.description}</p><small>输入：{skill.input}<br />输出：{skill.output}</small></div>)}</details>}{!!message.attachments?.length && <div className="assistant-file-labels">{message.attachments.map(name => <span key={name}><Paperclip size={12} />{name}</span>)}</div>}</div>)}{busy && <p className="helper-text"><LoaderCircle size={14} className="spin" />正在生成模拟回复…</p>}<div ref={bottom} /></div>
      <div className="assistant-composer">{!!files.length && <div className="assistant-attachments" aria-label="本次待发送附件">{files.map((file, index) => <span className="knowledge-chip" key={file.name}>{file.name}<button className="icon-button" disabled={busy} aria-label={`移除本次附件 ${file.name}`} onClick={() => setFiles(previous => previous.filter((_, i) => i !== index))}><X size={12} /></button></span>)}</div>}<textarea aria-label="向智能助手提问" placeholder="输入需求，回车发送…（Shift+Enter 换行）" maxLength={8000} value={text} disabled={busy} onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} /><div className="assistant-composer-actions"><label className={`assistant-upload ${busy ? 'disabled' : ''}`}><Paperclip size={17} /><span>上传文件</span><input type="file" multiple accept={resourceExtensions.join(',')} disabled={busy} aria-label="上传本次对话文件" onChange={event => { addFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} /></label><span>单文件及总大小 ≤50MB</span><button className="button primary small" disabled={busy || (!text.trim() && !files.length)} onClick={() => void send()}><Send size={14} />发送</button></div>{error && <p className="field-error" role="alert">{error}</p>}</div>
    </aside>}
    {picking && <Dialog wide title="加载 Skill 到对话台" onClose={() => setPicking(false)} footer={<button className="button" onClick={() => setPicking(false)}>完成</button>}><p className="helper-text">搜索并加载 Skill 后，可按统一输入输出契约开展对话。当前为前端模拟。</p><div className="catalog-filters"><input aria-label="助手技能名称搜索" placeholder="名称模糊搜索" value={filters.name} onChange={event => setFilters(previous => ({ ...previous, name: event.target.value }))} /><select aria-label="助手技能类" value={filters.classId} onChange={event => setFilters(previous => ({ ...previous, classId: event.target.value }))}><option value="">全部技能类</option>{skillClasses.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select><select aria-label="助手所属应用" value={filters.application} onChange={event => setFilters(previous => ({ ...previous, application: event.target.value }))}><option value="">全部应用</option>{applications.map(app => <option key={app.id}>{app.name}</option>)}</select><SearchSelect label="助手维护人" value={filters.maintainer} options={[...new Set(catalog.map(row => row.creatorName).filter((name): name is string => !!name))].map(name => ({ id: name, name }))} placeholder="全部维护人" onChange={value => setFilters(old => ({ ...old, maintainer: value }))} /><button className="button primary" onClick={() => setApplied(filters)}>搜索</button><button className="button" onClick={() => { setFilters({ name: '', classId: '', application: '', maintainer: '' }); setApplied({ name: '', classId: '', application: '', maintainer: '' }) }}>重置</button></div><div className="assistant-skill-results">{results.map(skill => <article key={skill.id}><div><h3>{skill.name}</h3><p>{skill.description}</p><div className="knowledge-selected"><span className="status-tag blue">{skillClasses.find(row => row.id === skill.classId)?.name}</span><span className="status-tag green">{applicationText(skill)}</span><span className="helper-text">维护人 {skill.creatorName || '历史维护人'}</span></div></div><button className="button small" disabled={busy || skillIds.includes(skill.id)} onClick={() => setSkillIds(previous => [...previous, skill.id])}>{skillIds.includes(skill.id) ? '已加载' : '加载'}</button></article>)}{!results.length && <p className="empty-table">未找到匹配的已上线技能。</p>}</div></Dialog>}
  </>
}
