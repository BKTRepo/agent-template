import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { Bot, Check, ChevronDown, ChevronLeft, Copy, History, LoaderCircle, Maximize2, MessageSquarePlus, Minimize2, Paperclip, Plus, RotateCcw, Send, Sparkles, Square, Star, ThumbsDown, ThumbsUp, Trash2, X } from 'lucide-react'
import Dialog from '@/components/developer/Dialog'
import SearchSelect from '@/components/developer/SearchSelect'
import { applications, applicationText } from '@/lib/access'
import { validateResourceFiles } from '@/lib/skillForm'
import { skillCatalog } from '@/lib/skillCatalog'
import { skillClasses } from '@/mocks/developerData'
import { useDeveloperStore } from '@/stores/developerStore'
import { useKnowledgeStore } from '@/stores/knowledgeStore'
import { chatFileExtensions, chatFileLimits, clearChatConversation, createChatConversation, deleteChatConversation, favoriteChatConversation, getChatConversation, listChatConversations, listChatMessages, listChatModelHealth, listChatModels, readChatConversation, retryChatTask, saveChatResources, sendChatFeedback, sendChatMessage, stopChatTask, streamChatTask, type AssistantMessage, type ChatConversation, type ChatModel, type ChatModelHealth, type ChatTask } from '@/api/assistant'

type ReplyStatus = 'generating' | 'completed' | 'stopped' | 'failed'
type ChatMessage = AssistantMessage & { status?: ReplyStatus; taskId?: number; feedback?: 'up' | 'down' }
type ActiveTask = { taskId: number; conversationId: string; messageId: number; controller: AbortController }

const suggestions = [['用例', '为当前对象生成正向 / 异常 / 边界用例'], ['缺陷', '分析最近一次失败调用的根因与修复建议'], ['契约', '核对当前接口契约与实际返回的一致性']] as const
const serverId = (value?: string) => { const id = Number(value); return Number.isInteger(id) && id > 0 ? id : undefined }
const statusOf = (task: ChatTask): ReplyStatus => task.status === 'success' ? 'completed' : task.status === 'cancelled' ? 'stopped' : task.status === 'failed' ? 'failed' : 'generating'
const sessionPreview = (messages: ChatMessage[]) => messages.at(-1)?.text.replace(/\s+/g, ' ').slice(0, 34) || '尚未开始对话'

export default function FloatingAssistant({ contextLabel = '当前页面' }: { contextLabel?: string }) {
  const implementations = useDeveloperStore(state => state.implementations)
  const knowledgeBases = useKnowledgeStore(state => state.knowledgeBases)
  const loadKnowledgeBases = useKnowledgeStore(state => state.load)
  const catalog = skillCatalog(implementations, true).filter(row => !!serverId(row.backendSkillId || row.id) && skillClasses.find(kind => kind.id === row.classId)?.enabled !== false)
  const [open, setOpen] = useState(false), [maximized, setMaximized] = useState(false), [drawer, setDrawer] = useState(false)
  const [sessions, setSessions] = useState<ChatConversation[]>([]), [activeId, setActiveId] = useState(''), [messages, setMessages] = useState<Record<string, ChatMessage[]>>({})
  const [skillIds, setSkillIds] = useState<string[]>([]), [knowledgeIds, setKnowledgeIds] = useState<string[]>([]), [model, setModel] = useState<string | null>(null), [models, setModels] = useState<ChatModel[]>([]), [modelHealth, setModelHealth] = useState<Record<string, ChatModelHealth>>({})
  const [pickingSkills, setPickingSkills] = useState(false), [pickingKnowledge, setPickingKnowledge] = useState(false), [modelOpen, setModelOpen] = useState(false), [files, setFiles] = useState<File[]>([]), [text, setText] = useState('')
  const [task, setTask] = useState<ActiveTask>(), [error, setError] = useState(''), [notice, setNotice] = useState(''), [loading, setLoading] = useState(false)
  const [offset, setOffset] = useState({ x: 0, y: 0 }), [filters, setFilters] = useState({ name: '', classId: '', application: '', maintainer: '' }), [applied, setApplied] = useState({ name: '', classId: '', application: '', maintainer: '' })
  const trigger = useRef<HTMLButtonElement>(null), bottom = useRef<HTMLDivElement>(null), loaded = useRef(false), taskRef = useRef<ActiveTask | undefined>(undefined), triggerDragged = useRef(false)
  const drag = useRef<{ x: number; y: number; offsetX: number; offsetY: number; source: 'panel' | 'trigger' } | null>(null)
  const active = sessions.find(session => session.id === activeId)
  const activeMessages = active ? messages[active.id] ?? [] : []
  const selectedSkills = catalog.filter(row => skillIds.includes(row.id))
  const selectedKnowledge = knowledgeBases.filter(row => knowledgeIds.includes(row.id))
  const modelLabel = model ? models.find(item => item.name === model)?.displayName || model : '自动'
  const healthFor = (name: string) => modelHealth[name]
  const modelTier = (name: string) => {
    const health = healthFor(name)
    if (!health || health.status === 'checking' || health.refreshing) return '检测中'
    if (health.status === 'busy') return '繁忙'
    if (health.status === 'unavailable' || health.status === 'unconfigured') return '不可用'
    if (health.stale) return '状态待刷新'
    if ((health.latencyMs ?? Infinity) <= 1500) return '极速'
    if ((health.latencyMs ?? Infinity) <= 4000) return '标准'
    return '较慢'
  }
  const modelDescription = (name: string) => { const health = healthFor(name); if (!health) return '正在读取健康状态'; if (health.status === 'healthy' && health.latencyMs !== null) return `健康 · 最近响应 ${health.latencyMs} ms`; if (health.status === 'checking') return '正在进行后端健康检测'; return health.status === 'busy' ? '后端当前繁忙，请稍后重试' : '后端当前不可用' }
  const busy = !!task, unread = sessions.reduce((total, row) => total + row.unreadCount, 0)
  const state = busy ? 'busy' : unread ? 'unread' : error ? 'error' : 'idle'
  const results = useMemo(() => catalog.filter(row => row.name.toLowerCase().includes(applied.name.trim().toLowerCase()) && (!applied.classId || row.classId === applied.classId) && (!applied.application || (row.applicationIds ?? [row.system]).some(id => id === '*' || id === applied.application)) && (!applied.maintainer || row.creatorName === applied.maintainer)), [catalog, applied])

  useEffect(() => { taskRef.current = task }, [task])
  useEffect(() => () => taskRef.current?.controller.abort(), [])
  useEffect(() => { if (open) bottom.current?.scrollIntoView({ block: 'nearest' }) }, [open, activeId, activeMessages.length, task])
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(''), 2200); return () => window.clearTimeout(timer) }, [notice])
  useEffect(() => { const move = (event: PointerEvent) => { if (!drag.current) return; const dx = event.clientX - drag.current.x, dy = event.clientY - drag.current.y; if (drag.current.source === 'trigger' && Math.hypot(dx, dy) > 4) triggerDragged.current = true; setOffset({ x: drag.current.offsetX + dx, y: drag.current.offsetY + dy }) }; const end = () => { drag.current = null }; window.addEventListener('pointermove', move); window.addEventListener('pointerup', end); return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end) } }, [])

  function patchSession(row: ChatConversation) { setSessions(items => [row, ...items.filter(item => item.id !== row.id)].sort((a, b) => +new Date(b.updatedAt) - +new Date(a.updatedAt))) }
  function updateMessages(conversationId: string, update: (items: ChatMessage[]) => ChatMessage[]) { setMessages(current => ({ ...current, [conversationId]: update(current[conversationId] ?? []) })) }
  function updateMessage(conversationId: string, messageId: string, update: (message: ChatMessage) => ChatMessage) { updateMessages(conversationId, items => items.map(item => item.id === messageId ? update(item) : item)) }
  async function loadConversation(conversationId: string) {
    setLoading(true); setError('')
    try {
      const [conversation, history] = await Promise.all([getChatConversation(conversationId), listChatMessages(conversationId)])
      patchSession({ ...conversation, unreadCount: 0 }); setActiveId(conversationId); setSkillIds(catalog.filter(item => conversation.skills.includes(serverId(item.backendSkillId || item.id)!)).map(item => item.id)); setKnowledgeIds(conversation.knowledgeBases.map(String)); setModel(conversation.model); setMessages(current => ({ ...current, [conversationId]: history })); setFiles([]); setText('')
      await readChatConversation(conversationId); setSessions(items => items.map(item => item.id === conversationId ? { ...item, unreadCount: 0 } : item))
    } catch (reason) { setError((reason as Error).message) } finally { setLoading(false) }
  }
  async function openPanel() {
    setOpen(true); setError('')
    if (loaded.current) return
    setLoading(true)
    try {
      const [history, availableModels, health] = await Promise.all([listChatConversations(), listChatModels(), listChatModelHealth().catch(() => []), loadKnowledgeBases()])
      loaded.current = true; setSessions(history.items); setModels(availableModels); setModelHealth(Object.fromEntries(health.map(item => [item.model, item])))
      if (health.some(item => item.status === 'checking' || item.refreshing)) window.setTimeout(() => { void listChatModelHealth().then(items => setModelHealth(Object.fromEntries(items.map(item => [item.model, item])))).catch(() => undefined) }, 1600)
      if (history.items[0]) await loadConversation(history.items[0].id)
    } catch (reason) { setError((reason as Error).message) } finally { setLoading(false) }
  }
  function close() { setOpen(false); setDrawer(false); trigger.current?.focus() }
  async function newSession() {
    if (busy) { setNotice('请先等待当前回复结束，或停止生成。'); return }
    setLoading(true); setError('')
    try { const conversation = await createChatConversation(); patchSession(conversation); setActiveId(conversation.id); setMessages(current => ({ ...current, [conversation.id]: [] })); setSkillIds([]); setKnowledgeIds([]); setModel(null); setFiles([]); setText(''); setDrawer(false) }
    catch (reason) { setError((reason as Error).message) } finally { setLoading(false) }
  }
  async function ensureConversation(title: string) {
    if (active) return active
    const conversation = await createChatConversation(title.trim().slice(0, 30) || '新对话'); patchSession(conversation); setActiveId(conversation.id); setMessages(current => ({ ...current, [conversation.id]: [] })); return conversation
  }
  function skillNumbers(ids = skillIds) { return ids.map(id => catalog.find(item => item.id === id)).map(item => serverId(item?.backendSkillId || item?.id)).filter((id): id is number => !!id) }
  async function persistResources(conversation: ChatConversation, next = { skills: skillIds, knowledge: knowledgeIds, selectedModel: model }) {
    const kbIds = next.knowledge.map(serverId).filter((id): id is number => !!id)
    const saved = await saveChatResources(conversation.id, { skills: skillNumbers(next.skills), knowledgeBases: kbIds, model: next.selectedModel }); patchSession(saved); return saved
  }
  async function changeResources(change: { skills?: string[]; knowledge?: string[]; selectedModel?: string | null }) {
    const next = { skills: change.skills ?? skillIds, knowledge: change.knowledge ?? knowledgeIds, selectedModel: change.selectedModel === undefined ? model : change.selectedModel }
    if (!active) { setSkillIds(next.skills); setKnowledgeIds(next.knowledge); setModel(next.selectedModel); return }
    try { const saved = await persistResources(active, next); setSkillIds(catalog.filter(item => saved.skills.includes(serverId(item.backendSkillId || item.id)!)).map(item => item.id)); setKnowledgeIds(saved.knowledgeBases.map(String)); setModel(saved.model) }
    catch (reason) { setError((reason as Error).message) }
  }
  async function clearSession() {
    if (!active || busy) return
    try { const saved = await clearChatConversation(active.id); patchSession(saved); setMessages(current => ({ ...current, [active.id]: [] })); setError(''); setNotice('已清空当前会话') } catch (reason) { setError((reason as Error).message) }
  }
  async function removeSession(conversationId: string) {
    if (busy) { setNotice('请先等待当前回复结束，或停止生成。'); return }
    try { await deleteChatConversation(conversationId); const rest = sessions.filter(row => row.id !== conversationId); setSessions(rest); setMessages(current => { const next = { ...current }; delete next[conversationId]; return next }); if (conversationId === activeId) { setActiveId(''); setSkillIds([]); setKnowledgeIds([]); setModel(null); if (rest[0]) void loadConversation(rest[0].id) } } catch (reason) { setError((reason as Error).message) }
  }
  async function toggleFavorite(conversation: ChatConversation) { try { patchSession(await favoriteChatConversation(conversation.id, !conversation.favorite)) } catch (reason) { setError((reason as Error).message) } }
  function addFiles(incoming: File[]) { const existing = files.map((file, index) => ({ id: String(index), name: file.name, size: file.size, lastModified: file.lastModified })); const result = validateResourceFiles(incoming, existing, chatFileExtensions, chatFileLimits); setFiles(previous => [...previous, ...result.accepted]); setError(result.errors.join('；')) }
  function applyTask(conversationId: string, messageId: string, current: ChatTask) { updateMessage(conversationId, messageId, message => ({ ...message, text: current.content || (current.status === 'failed' ? current.error || '生成失败，请稍后重试。' : message.text), status: statusOf(current), taskId: current.taskId, serverId: current.messageId })) }
  async function followTask(running: ActiveTask) {
    try { await streamChatTask(running.taskId, result => applyTask(running.conversationId, String(running.messageId), result), running.controller.signal) }
    catch (reason) { if (!running.controller.signal.aborted) { const message = (reason as Error).message || '生成失败，请稍后重试。'; updateMessage(running.conversationId, String(running.messageId), item => ({ ...item, status: 'failed', text: message })); setError(message) } }
    finally { setTask(current => current?.taskId === running.taskId ? undefined : current) }
  }
  async function send(prompt = text, selectedFiles = files) {
    if (busy || (!prompt.trim() && !selectedFiles.length)) return
    setError('')
    try {
      const conversation = await ensureConversation(prompt); const saved = await persistResources(conversation)
      const sent = await sendChatMessage(saved.id, prompt, saved.model, selectedFiles)
      const user: ChatMessage = { id: `local-${Date.now()}`, role: 'user', text: prompt.trim() || '请结合本次上传文件协助分析。', attachments: selectedFiles.map(file => file.name) }
      const assistant: ChatMessage = { id: String(sent.messageId), serverId: sent.messageId, taskId: sent.taskId, role: 'assistant', text: '', status: 'generating' }
      updateMessages(saved.id, rows => [...rows, user, assistant]); setFiles([]); setText('')
      const running = { taskId: sent.taskId, conversationId: saved.id, messageId: sent.messageId, controller: new AbortController() }; setTask(running); void followTask(running)
    } catch (reason) { setError((reason as Error).message) }
  }
  async function stop() { if (!task) return; try { applyTask(task.conversationId, String(task.messageId), await stopChatTask(task.taskId)); setNotice('已请求停止，正在等待服务端结束任务。') } catch (reason) { setError((reason as Error).message) } }
  async function retry(message: ChatMessage) {
    if (busy || !message.taskId || !active) return
    try { const sent = await retryChatTask(message.taskId); const oldId = message.id; updateMessage(active.id, oldId, item => ({ ...item, id: String(sent.messageId), serverId: sent.messageId, taskId: sent.taskId, text: '', status: 'generating', feedback: undefined })); const running = { taskId: sent.taskId, conversationId: active.id, messageId: sent.messageId, controller: new AbortController() }; setTask(running); void followTask(running) } catch (reason) { setError((reason as Error).message) }
  }
  async function feedback(message: ChatMessage, rating: 'up' | 'down') { if (!message.serverId) return; try { await sendChatFeedback(message.serverId, rating === 'up' ? 'like' : 'dislike'); updateMessage(activeId, message.id, item => ({ ...item, feedback: item.feedback === rating ? undefined : rating })); setNotice('感谢反馈') } catch (reason) { setError((reason as Error).message) } }
  async function copy(textToCopy: string) { try { await navigator.clipboard.writeText(textToCopy); setNotice('已复制到剪贴板') } catch { setNotice('浏览器未授予剪贴板权限') } }
  function startDrag(event: ReactPointerEvent<HTMLElement>) {
    const target = event.target as Element
    if (maximized || target.closest('button, input, textarea, label, select, .aip-messages, .aip-composer, .aip-session-drawer, [role="dialog"]')) return
    event.preventDefault()
    drag.current = { x: event.clientX, y: event.clientY, offsetX: offset.x, offsetY: offset.y, source: 'panel' }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  function startTriggerDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    triggerDragged.current = false
    drag.current = { x: event.clientX, y: event.clientY, offsetX: offset.x, offsetY: offset.y, source: 'trigger' }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  function toggleTrigger() { if (triggerDragged.current) { triggerDragged.current = false; return } if (open) close(); else void openPanel() }

  return <>
    <div className={`assistant-float ${maximized ? 'maxed' : ''}`} style={!maximized && (offset.x || offset.y) ? { transform: `translate(${offset.x}px, ${offset.y}px)` } : undefined}>
      <button ref={trigger} className={`assistant-trigger ${open ? 'is-open' : ''}`} data-state={state} aria-label={open ? '收起智能助手' : '打开智能助手'} aria-expanded={open} onPointerDown={startTriggerDrag} onClick={toggleTrigger}><span className="assistant-ring" /><span className="aip-orb-bot" aria-hidden="true"><svg viewBox="0 0 100 100" width="46" height="46"><path d="M31 26Q21 8 39 12Q33 18 37 28Z" fill="#fbfdfd" stroke="#d5e0dd" strokeWidth="1.5" /><path d="M69 26Q79 8 61 12Q67 18 63 28Z" fill="#fbfdfd" stroke="#d5e0dd" strokeWidth="1.5" /><ellipse cx="50" cy="55" rx="42" ry="39" fill="#f1f5f3" stroke="#d5e0dd" strokeWidth="1.5" /><path d="M11 62Q50 84 89 62Q84 88 50 91Q16 88 11 62Z" fill="#dde7e4" /><rect x="26" y="38" width="48" height="34" rx="16" fill="#22434b" /><rect className="aip-eye" x="39.5" y="45" width="9.5" height="20" rx="4.7" fill="#fff" /><rect className="aip-eye" x="51" y="45" width="9.5" height="20" rx="4.7" fill="#fff" /></svg></span><span className="aip-orb-close" aria-hidden="true"><X size={25} /></span>{!!unread && <span className="assistant-badge">{unread > 99 ? '99+' : unread}</span>}<span className="assistant-tip"><b>{busy ? '正在生成' : unread ? `${unread} 条新回复` : 'AI 助手'}</b><i>{busy ? '可转入后台继续处理' : '全局可用'}</i></span></button>
      {open && <aside className={`assistant-panel aip-panel ${maximized ? 'aip-maximized' : ''}`} role="dialog" aria-label="平台级 AI 助手" aria-modal="false" data-page-context={contextLabel} onPointerDown={startDrag}>
        <header className="aip-header"><span className="aip-avatar"><span className="aip-avatar-face">AI</span></span><div className="aip-brand"><div className="aip-title">平台级 AI 助手 <span>全局</span></div><div className="aip-sub"><i />{busy ? '正在生成回复…' : loading ? '正在加载服务端会话…' : '已连接对话服务'}</div></div><div className="aip-head-actions"><button className={drawer ? 'on' : ''} aria-label="查看会话" title="会话" onPointerDown={event => event.stopPropagation()} onClick={() => setDrawer(value => !value)}><History size={15} />{unread > 0 && <i className="aip-unread-dot" />}</button><button aria-label="新建会话" title="新建会话" disabled={loading} onPointerDown={event => event.stopPropagation()} onClick={() => void newSession()}><MessageSquarePlus size={15} /></button><button aria-label={maximized ? '还原窗口' : '最大化窗口'} title={maximized ? '还原窗口' : '最大化窗口'} onPointerDown={event => event.stopPropagation()} onClick={() => setMaximized(value => !value)}>{maximized ? <Minimize2 size={15} /> : <Maximize2 size={15} />}</button><button className="aip-close" aria-label="关闭助手" title="关闭" onPointerDown={event => event.stopPropagation()} onClick={close}><X size={16} /></button></div></header>
        <section className="aip-resources" aria-label="本次会话资源"><div><b>SKILL</b><span>{selectedSkills.length ? selectedSkills.map(skill => <em key={skill.id}><Sparkles size={11} />{skill.name}<button disabled={busy} aria-label={`移除 ${skill.name}`} onClick={() => void changeResources({ skills: skillIds.filter(id => id !== skill.id) })}>×</button></em>) : <small>未加载 · 使用通用对话</small>}<button className="aip-add" disabled={busy} onClick={() => setPickingSkills(true)}>+ 加载</button></span></div><div><b>知识库</b><span>{selectedKnowledge.length ? selectedKnowledge.map(item => <em key={item.id}><Check size={11} />{item.name}<button disabled={busy} aria-label={`移除 ${item.name}`} onClick={() => void changeResources({ knowledge: knowledgeIds.filter(id => id !== item.id) })}>×</button></em>) : <small>未挂载</small>}<button className="aip-add" disabled={busy} onClick={() => setPickingKnowledge(true)}>+ 挂载</button></span></div></section>
        <div className="aip-messages" role="log" aria-live="polite">{loading && !active ? <p className="aip-working"><LoaderCircle size={13} className="spin" />正在加载会话记录…</p> : !activeMessages.length && <section className="aip-welcome"><h3>你好，我是平台级 AI 入口</h3><p>消息、会话、已选资源和模型均保存到后端；可加载已上线 Skill 后发起真实任务。</p><div>{suggestions.map(([tag, value]) => <button key={tag} onClick={() => setText(value)}><span>{tag}</span>{value}</button>)}</div></section>}{activeMessages.map(message => message.role === 'user' ? <article className="aip-message user" key={message.id}><p>{message.text}</p>{message.attachments?.length ? <div className="aip-message-meta">{message.attachments.map(name => <span key={name}><Paperclip size={11} />{name}</span>)}</div> : null}</article> : <article className={`aip-message bot ${message.status ?? 'completed'}`} key={message.id}>{message.status === 'generating' ? <><header><Sparkles size={14} /><b>对话服务 · 生成中</b><span>流式返回</span></header><div className="aip-progress"><i /></div>{message.text ? <p>{message.text}</p> : <p className="aip-working"><LoaderCircle size={13} className="spin" />正在调用后端模型…</p>}<footer>{task?.taskId === message.taskId && <button className="aip-action danger" onClick={() => void stop()}><Square size={12} />停止生成</button>}<button className="aip-action ghost" onClick={close}>转入后台</button></footer></> : <><header>{message.status === 'failed' ? <X size={14} /> : message.status === 'stopped' ? <Square size={13} /> : <Check size={14} />}<b>{message.status === 'failed' ? '生成失败' : message.status === 'stopped' ? '已停止生成' : 'AI 助手'}</b><span>{message.status === 'completed' ? '已完成' : ''}</span></header><p>{message.text}</p><footer><button className="aip-action" onClick={() => void copy(message.text)}><Copy size={12} />复制</button>{message.taskId && <button className="aip-action" disabled={busy} onClick={() => void retry(message)}><RotateCcw size={12} />重新生成</button>}{message.status === 'completed' && <span className="aip-feedback"><button className={message.feedback === 'up' ? 'selected up' : ''} aria-label="有帮助" onClick={() => void feedback(message, 'up')}><ThumbsUp size={13} /></button><button className={message.feedback === 'down' ? 'selected down' : ''} aria-label="需改进" onClick={() => void feedback(message, 'down')}><ThumbsDown size={13} /></button></span>}</footer></>}</article>)}<div ref={bottom} /></div>
        <section className="aip-composer"><div className="aip-attachments">{files.map((file, index) => <span key={`${file.name}-${index}`}><Paperclip size={11} />{file.name}<button disabled={busy} aria-label={`移除 ${file.name}`} onClick={() => setFiles(current => current.filter((_, fileIndex) => fileIndex !== index))}>×</button></span>)}</div><div className="aip-input"><textarea aria-label="向智能助手提问" placeholder="描述你的诉求，Enter 发送，Shift + Enter 换行" maxLength={40000} value={text} disabled={busy} onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} /><div><label className={busy ? 'disabled' : ''}><Paperclip size={16} /><input type="file" multiple accept={chatFileExtensions.join(',')} disabled={busy} aria-label="上传本次对话文件" onChange={event => { addFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} /></label><small>单文件 ≤ 20 MB，最多 10 个</small><span className="aip-model-picker"><button className={`aip-model ${modelOpen ? 'on' : ''}`} type="button" aria-label="选择对话模型" aria-haspopup="dialog" aria-expanded={modelOpen} disabled={busy} onClick={() => setModelOpen(value => !value)}><Sparkles size={12} /><span>{modelLabel}</span><ChevronDown size={12} /></button>{modelOpen && <span className="aip-model-pop" role="dialog" aria-label="模型选择"><b>模型 · 能力与成本的权衡</b><button className={!model ? 'selected' : ''} onClick={() => { setModelOpen(false); void changeResources({ selectedModel: null }) }}><span><strong>自动 <em>推荐</em></strong><small>按诉求复杂度、已加载 Skill 和知识库自动选择健康模型</small></span>{!model && <Check size={16} />}</button>{models.map(item => <button key={item.name} className={model === item.name ? 'selected' : ''} disabled={['unavailable', 'unconfigured'].includes(healthFor(item.name)?.status ?? '')} onClick={() => { setModelOpen(false); void changeResources({ selectedModel: item.name }) }}><span><strong>{item.displayName}<em className={`model-tier ${healthFor(item.name)?.status ?? 'checking'}`}>{modelTier(item.name)}</em></strong><small>{modelDescription(item.name)}</small></span>{model === item.name && <Check size={16} />}</button>)}<i>健康状态由后端实时检测；自动分配会在结果中标注实际使用的模型</i></span>}</span>{busy ? <button className="aip-stop" onClick={() => void stop()}><Square size={12} />停止</button> : <button className="aip-send" disabled={!text.trim() && !files.length} onClick={() => void send()}><Send size={13} />发送</button>}</div></div>{error && <p className="aip-error" role="alert">{error}</p>}</section>
        {drawer && <aside className="aip-session-drawer" aria-label="会话列表"><header><button aria-label="返回对话" onClick={() => setDrawer(false)}><ChevronLeft size={18} /></button><b>服务端会话记录</b><button className="aip-new-session" onClick={() => void newSession()}><Plus size={14} />新建</button></header><div>{sessions.slice().sort((a, b) => Number(b.favorite) - Number(a.favorite) || +new Date(b.updatedAt) - +new Date(a.updatedAt)).map(session => <article key={session.id} className={session.id === activeId ? 'active' : ''} onClick={() => void loadConversation(session.id)}><button className={session.favorite ? 'favorite' : ''} aria-label={session.favorite ? '取消收藏' : '收藏会话'} onClick={event => { event.stopPropagation(); void toggleFavorite(session) }}><Star size={13} /></button><div><b>{session.title}</b><p>{sessionPreview(messages[session.id] ?? [])}</p></div>{session.unreadCount ? <i>{session.unreadCount}</i> : null}<button className="delete" aria-label="删除会话" onClick={event => { event.stopPropagation(); void removeSession(session.id) }}><Trash2 size={13} /></button></article>)}</div>{active && <button className="aip-action" disabled={busy} onClick={() => void clearSession()}>清空当前会话</button>}</aside>}
      </aside>}
    </div>
    {notice && <div className="aip-toast" role="status">{notice}</div>}
    {pickingSkills && <Dialog wide title="加载 Skill 到对话台" onClose={() => setPickingSkills(false)} footer={<button className="button" onClick={() => setPickingSkills(false)}>完成</button>}><p className="helper-text">仅展示有真实后端编号的已上线技能。选择后通过 /chat/conversation/resources 保存到当前会话。</p><div className="catalog-filters"><input aria-label="助手技能名称搜索" placeholder="名称模糊搜索" value={filters.name} onChange={event => setFilters(current => ({ ...current, name: event.target.value }))} /><select aria-label="助手技能类" value={filters.classId} onChange={event => setFilters(current => ({ ...current, classId: event.target.value }))}><option value="">全部技能类</option>{skillClasses.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select><select aria-label="助手所属应用" value={filters.application} onChange={event => setFilters(current => ({ ...current, application: event.target.value }))}><option value="">全部应用</option>{applications.map(app => <option key={app.id}>{app.name}</option>)}</select><SearchSelect label="助手维护人" value={filters.maintainer} options={[...new Set(catalog.map(row => row.creatorName).filter((name): name is string => !!name))].map(name => ({ id: name, name }))} placeholder="全部维护人" onChange={value => setFilters(current => ({ ...current, maintainer: value }))} /><button className="button primary" onClick={() => setApplied(filters)}>搜索</button></div><div className="assistant-skill-results">{results.map(skill => <article key={skill.id}><div><h3>{skill.name}</h3><p>{skill.description}</p><div className="knowledge-selected"><span className="status-tag blue">{skillClasses.find(row => row.id === skill.classId)?.name}</span><span className="status-tag green">{applicationText(skill)}</span></div></div><button className="button small" disabled={busy || skillIds.includes(skill.id)} onClick={() => void changeResources({ skills: [...skillIds, skill.id] })}>{skillIds.includes(skill.id) ? '已加载' : '加载'}</button></article>)}{!results.length && <p className="empty-table">未找到可用于悬浮对话的已上线技能。</p>}</div></Dialog>}
    {pickingKnowledge && <Dialog wide title="挂载知识库到对话台" onClose={() => setPickingKnowledge(false)} footer={<button className="button" onClick={() => setPickingKnowledge(false)}>完成</button>}><p className="helper-text">只可选择已处理完成、且当前账号有权限的知识库；选择后通过真实会话资源接口保存。</p><div className="assistant-skill-results">{knowledgeBases.filter(item => item.processingStatus === '知识处理完成' && !!serverId(item.id)).map(item => <article key={item.id}><div><h3>{item.name}</h3><p>{item.description || '暂无描述'}</p></div><button className="button small" disabled={busy || knowledgeIds.includes(item.id)} onClick={() => void changeResources({ knowledge: [...knowledgeIds, item.id] })}>{knowledgeIds.includes(item.id) ? '已挂载' : '挂载'}</button></article>)}{!knowledgeBases.filter(item => item.processingStatus === '知识处理完成' && !!serverId(item.id)).length && <p className="empty-table">暂无可挂载的已处理完成知识库。</p>}</div></Dialog>}
  </>
}
