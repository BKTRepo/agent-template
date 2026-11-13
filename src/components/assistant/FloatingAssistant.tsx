import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { Bot, Check, ChevronDown, ChevronLeft, Copy, FileText, History, ListTodo, Settings, LoaderCircle, Maximize2, MessageSquarePlus, Minimize2, Paperclip, Plus, RotateCcw, Send, Sparkles, Square, Star, ThumbsDown, ThumbsUp, Trash2, X } from 'lucide-react'
import { createPortal } from 'react-dom'
import AssistantSessions from './AssistantSessions'
import AssistantFeedback from './AssistantFeedback'
import useAssistantGeometry from './useAssistantGeometry'
import Dialog from '@/components/developer/Dialog'
import { useAssistantContextStore, type AssistantModule } from '@/stores/assistantContextStore'
import ArtifactDemo from './ArtifactDemo'
import ArtifactWorkbench from './ArtifactWorkbench'
import AssistantResourcePicker from './AssistantResourcePicker'
import { getCatalogSkill } from '@/api/skillCatalog'
import { getKnowledgeBase } from '@/api/knowledge'
import type { Implementation, KnowledgeBase } from '@/types/developer'
import { copyText } from '@/lib/clipboard'
import { validateResourceFiles } from '@/lib/skillForm'
import { deleteAllChatConversations, listChatTasks, chatFileExtensions, chatFileLimits, clearChatConversation, createChatConversation, deleteChatConversation, favoriteChatConversation, getChatConversation, listChatConversations, listChatMessages, listChatModelHealth, listChatModels, readChatConversation, retryChatTask, saveChatResources, sendChatFeedback, sendChatMessage, stopChatTask, streamChatTask, type AssistantMessage, type ChatConversation, type ChatModel, type ChatModelHealth, type ChatTask } from '@/api/assistant'

type ReplyStatus = 'generating' | 'completed' | 'stopped' | 'failed'
type ChatMessage = AssistantMessage & { status?: ReplyStatus; taskId?: number; feedback?: 'up' | 'down' }
type TaskRow = ChatTask & { conversationId: string }
type ActiveTask = { taskId: number; conversationId: string; messageId: number; controller: AbortController }

const suggestions = [['用例', '为当前对象生成正向 / 异常 / 边界用例'], ['缺陷', '分析最近一次失败调用的根因与修复建议'], ['契约', '核对当前接口契约与实际返回的一致性']] as const
const serverId = (value?: string) => { const id = Number(value); return Number.isInteger(id) && id > 0 ? id : undefined }
const statusOf = (task: ChatTask): ReplyStatus => task.status === 'success' ? 'completed' : task.status === 'cancelled' ? 'stopped' : task.status === 'failed' ? 'failed' : 'generating'

function knowledgeSources(skillIds: string[], catalog: Implementation[]) {
  const sources = new Map<string, string[]>()
  for (const skillId of skillIds) {
    const skill = catalog.find(item => item.id === skillId)
    const skillName = skill?.name ?? `技能 ${skillId}`
    for (const knowledge of skill?.knowledgeBases ?? []) {
      const knowledgeId = String(knowledge.id)
      if (!knowledgeId) continue
      sources.set(knowledgeId, [...(sources.get(knowledgeId) ?? []), skillName])
    }
  }
  return sources
}

function effectiveKnowledgeIds(skillIds: string[], manualKnowledgeIds: string[], catalog: Implementation[]) {
  return [...new Set([...knowledgeSources(skillIds, catalog).keys(), ...manualKnowledgeIds])]
}

const manualKnowledgeStorageKey = (conversationId: string) => `assistant.manual-knowledge.${conversationId}`
function readManualKnowledge(conversationId: string, availableIds: string[], automaticIds: Set<string>) {
  try {
    const stored = JSON.parse(window.localStorage.getItem(manualKnowledgeStorageKey(conversationId)) || 'null')
    if (Array.isArray(stored)) return [...new Set(stored.map(String).filter(id => availableIds.includes(id)))]
  } catch { /* 存储不可用时按服务端资源推断 */ }
  return availableIds.filter(id => !automaticIds.has(id))
}
function storeManualKnowledge(conversationId: string, ids: string[]) {
  try { window.localStorage.setItem(manualKnowledgeStorageKey(conversationId), JSON.stringify([...new Set(ids)])) } catch { /* 当前会话仍可正常使用 */ }
}
function removeStoredManualKnowledge(conversationId: string) {
  try { window.localStorage.removeItem(manualKnowledgeStorageKey(conversationId)) } catch { /* ignore */ }
}

export default function FloatingAssistant({ contextLabel = '当前页面', contextModule = 'developer' }: { contextLabel?: string; contextModule?: AssistantModule }) {
  const [catalog, setCatalog] = useState<Implementation[]>([])
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([])
  const [open, setOpen] = useState(false), [maximized, setMaximized] = useState(false), [drawer, setDrawer] = useState(false)
  const [sessions, setSessions] = useState<ChatConversation[]>([]), [activeId, setActiveId] = useState(''), [messages, setMessages] = useState<Record<string, ChatMessage[]>>({})
  const [skillIds, setSkillIds] = useState<string[]>([]), [manualKnowledgeIds, setManualKnowledgeIds] = useState<string[]>([]), [model, setModel] = useState<string | null>(null), [models, setModels] = useState<ChatModel[]>([]), [modelHealth, setModelHealth] = useState<Record<string, ChatModelHealth>>({})
  const [pickingSkills, setPickingSkills] = useState(false), [pickingKnowledge, setPickingKnowledge] = useState(false), [modelOpen, setModelOpen] = useState(false), [files, setFiles] = useState<File[]>([]), [text, setText] = useState('')
  const [selectedArtifactId, setSelectedArtifactId] = useState<string>()
  const [runningTasks, setRunningTasks] = useState<Record<number, ActiveTask>>({}), [taskRows, setTaskRows] = useState<TaskRow[]>([]), [error, setError] = useState(''), [notice, setNotice] = useState(''), [loading, setLoading] = useState(false)
  const { geometry, setGeometry, reset: resetGeometry } = useAssistantGeometry()
  const offset = geometry.offset
  const setOffset = (value: typeof offset) => setGeometry(previous => ({ ...previous, offset: value }))
  const [portalTarget, setPortalTarget] = useState<HTMLElement>()
  const [preferences, setPreferences] = useState(false), [taskListOpen, setTaskListOpen] = useState(false), [confirmClear, setConfirmClear] = useState(false)
  const [feedbackTarget, setFeedbackTarget] = useState<ChatMessage>(), [resendSource, setResendSource] = useState<number>()
  const resize = useRef<{ x: number; y: number; width: number; height: number } | null>(null)
  const trigger = useRef<HTMLButtonElement>(null), bottom = useRef<HTMLDivElement>(null), loaded = useRef(false), taskRef = useRef<Record<number, ActiveTask>>({}), taskProgressStarted = useRef<Record<number, number>>({}), triggerDragged = useRef(false)
  const drag = useRef<{ x: number; y: number; offsetX: number; offsetY: number; source: 'panel' | 'trigger'; bounds: DOMRect } | null>(null)
  const task = Object.values(runningTasks).find(item => item.conversationId === activeId)
  const active = sessions.find(session => session.id === activeId)
  const activeMessages = active ? messages[active.id] ?? [] : []
  const selectedSkills = skillIds.map(id => catalog.find(row => row.id === id) ?? { id, name: `不可用技能 ${id}` })
  const knowledgeSourceMap = knowledgeSources(skillIds, catalog)
  const knowledgeIds = effectiveKnowledgeIds(skillIds, manualKnowledgeIds, catalog)
  const selectedKnowledge = knowledgeIds.map(id => knowledgeBases.find(row => row.id === id) ?? catalog.flatMap(skill => skill.knowledgeBases ?? []).find(row => row.id === id) ?? { id, name: `不可用知识库 ${id}` })
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
  const busy = !!task || taskRows.some(item => item.conversationId === activeId && ['pending', 'running', 'cancelling', 'recovering'].includes(item.status)), unread = sessions.reduce((total, row) => total + row.unreadCount, 0)
  const state = Object.keys(runningTasks).length || taskRows.some(item => ['pending', 'running', 'cancelling', 'recovering'].includes(item.status)) ? 'busy' : unread ? 'unread' : error ? 'error' : 'idle'

  useEffect(() => { taskRef.current = runningTasks }, [runningTasks])
  useEffect(() => () => Object.values(taskRef.current).forEach(item => item.controller.abort()), [])
  useEffect(() => { if (open) bottom.current?.scrollIntoView({ block: 'nearest' }) }, [open, activeId, activeMessages.length, task])
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(''), 2200); return () => window.clearTimeout(timer) }, [notice])
  useEffect(() => {
    const activeTaskIds = [...Object.values(runningTasks).filter(item => item.conversationId === activeId).map(item => item.taskId), ...taskRows.filter(item => item.conversationId === activeId && ['pending', 'running', 'cancelling', 'recovering'].includes(item.status)).map(item => item.taskId)]
    if (!activeTaskIds.length) return
    const taskId = activeTaskIds[0]
    taskProgressStarted.current[taskId] ??= Date.now()
    const tick = () => {
      const elapsed = Date.now() - (taskProgressStarted.current[taskId] ?? Date.now())
      const progress = elapsed >= 120_000 ? 99 : Math.min(98, Math.floor(99 * (1 - Math.exp(-elapsed / 30_000))))
      setTaskProgress(progress)
    }
    tick()
    const timer = window.setInterval(tick, 400)
    return () => window.clearInterval(timer)
  }, [activeId, runningTasks, taskRows])
  useEffect(() => {
    if (!open) return
    const receivePastedImage = (event: ClipboardEvent) => {
      const target = event.target
      if (busy || loading || !(target instanceof HTMLTextAreaElement) || target.getAttribute('aria-label') !== '向智能助手提问') return
      if (addPastedImages(event.clipboardData?.items ?? null)) event.preventDefault()
    }
    document.addEventListener('paste', receivePastedImage)
    return () => document.removeEventListener('paste', receivePastedImage)
  }, [open, busy, loading, files])
  useEffect(() => { const move = (event: PointerEvent) => { if (resize.current) { const origin = resize.current; setGeometry(value => ({ ...value, size: { width: Math.max(320, Math.min(window.innerWidth - 24, origin.width - event.clientX + origin.x)), height: Math.max(320, Math.min(window.innerHeight - 104, origin.height - event.clientY + origin.y)) } })); return } if (!drag.current) return; const dx = event.clientX - drag.current.x, dy = event.clientY - drag.current.y; if (drag.current.source === 'trigger' && Math.hypot(dx, dy) > 4) triggerDragged.current = true; const bounds = drag.current.bounds; setOffset({ x: drag.current.offsetX + Math.max(8 - bounds.left, Math.min(window.innerWidth - bounds.right - 8, dx)), y: drag.current.offsetY + Math.max(8 - bounds.top, Math.min(window.innerHeight - bounds.bottom - 8, dy)) }) }; const end = () => { drag.current = null; resize.current = null }; window.addEventListener('pointermove', move); window.addEventListener('pointerup', end); return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end) } }, [])

  useEffect(() => {
    const update = () => {
      const dialogs = Array.from(document.querySelectorAll<HTMLDialogElement>('dialog[open]:not(.assistant-owned-dialog):not(.artifact-case-drawer):not(.ordinary-artifact-drawer)'))
      setPortalTarget(dialogs.at(-1))
    }
    update(); const observer = new MutationObserver(update)
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['open'] })
    return () => observer.disconnect()
  }, [])
  useEffect(() => { if (geometry.degrade && portalTarget) setOpen(false) }, [geometry.degrade, portalTarget])
  useEffect(() => {
    let disposed = false, polling = false
    const refresh = async () => {
      if (polling) return
      polling = true
      try {
        const [history, tasks] = await Promise.all([listChatConversations(), listChatTasks()])
        if (disposed) return
        setSessions(history.items); setTaskRows(tasks)
        for (const row of tasks) {
          applyTask(row.conversationId, String(row.messageId), row)
          if (open && row.conversationId === activeId && history.items.find(item => item.id === activeId)?.unreadCount) {
            await readChatConversation(activeId)
            setSessions(items => items.map(item => item.id === activeId ? { ...item, unreadCount: 0 } : item))
          }
        }
      } catch (reason) { if (!disposed) setError((reason as Error).message) } finally { polling = false }
    }
    void refresh(); const timer = window.setInterval(() => void refresh(), 3000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [open, activeId])
  function patchSession(row: ChatConversation) { setSessions(items => [row, ...items.filter(item => item.id !== row.id)].sort((a, b) => +new Date(b.updatedAt) - +new Date(a.updatedAt))) }
  function updateMessages(conversationId: string, update: (items: ChatMessage[]) => ChatMessage[]) { setMessages(current => ({ ...current, [conversationId]: update(current[conversationId] ?? []) })) }
  function updateMessage(conversationId: string, messageId: string, update: (message: ChatMessage) => ChatMessage) { updateMessages(conversationId, items => items.map(item => item.id === messageId ? update(item) : item)) }
  async function loadConversation(conversationId: string) {
    setLoading(true); setError('')
    try {
      const [conversation, history] = await Promise.all([getChatConversation(conversationId), listChatMessages(conversationId)])
      patchSession({ ...conversation, unreadCount: 0 }); setActiveId(conversationId); setSkillIds(conversation.skills.map(String)); setModel(conversation.model); setMessages(current => ({ ...current, [conversationId]: history })); setFiles([]); setText(''); setResendSource(undefined)
      const [skillDetails, knowledgeDetails] = await Promise.all([Promise.all(conversation.skills.map(id => getCatalogSkill(String(id)).catch(() => undefined))), Promise.all(conversation.knowledgeBases.map(id => getKnowledgeBase(String(id)).catch(() => undefined)))])
      const resolvedSkills = skillDetails.filter((item): item is Implementation => !!item)
      const automaticKnowledge = new Set(knowledgeSources(conversation.skills.map(String), resolvedSkills).keys())
      setCatalog(resolvedSkills); setKnowledgeBases(knowledgeDetails.filter((item): item is KnowledgeBase => !!item)); setManualKnowledgeIds(readManualKnowledge(conversation.id, conversation.knowledgeBases.map(String), automaticKnowledge))
      await readChatConversation(conversationId); setSessions(items => items.map(item => item.id === conversationId ? { ...item, unreadCount: 0 } : item))
    } catch (reason) { setError((reason as Error).message) } finally { setLoading(false) }
  }
  async function openPanel() {
    setOpen(true); setError('')
    if (loaded.current) return
    setLoading(true)
    try {
      const [history, availableModels, health] = await Promise.all([listChatConversations(), listChatModels(), listChatModelHealth().catch(() => [])])
      loaded.current = true; setSessions(history.items); setModels(availableModels); setModelHealth(Object.fromEntries(health.map(item => [item.model, item])))
      if (health.some(item => item.status === 'checking' || item.refreshing)) window.setTimeout(() => { void listChatModelHealth().then(items => setModelHealth(Object.fromEntries(items.map(item => [item.model, item])))).catch(() => undefined) }, 1600)
      if (history.items[0]) await loadConversation(history.items[0].id)
    } catch (reason) { setError((reason as Error).message) } finally { setLoading(false) }
  }
  function close() { setOpen(false); setDrawer(false); trigger.current?.focus() }
  async function newSession() {
    setLoading(true); setError('')
    try { const conversation = await createChatConversation(); patchSession(conversation); setActiveId(conversation.id); setMessages(current => ({ ...current, [conversation.id]: [] })); setSkillIds([]); setManualKnowledgeIds([]); setModel(null); setFiles([]); setText(''); setDrawer(false); setResendSource(undefined) }
    catch (reason) { setError((reason as Error).message) } finally { setLoading(false) }
  }
  async function ensureConversation(title: string) {
    if (active) return active
    const conversation = await createChatConversation(title.trim().slice(0, 30) || '新对话'); patchSession(conversation); setActiveId(conversation.id); setMessages(current => ({ ...current, [conversation.id]: [] })); return conversation
  }
  function skillNumbers(ids = skillIds) { return ids.map(serverId).filter((id): id is number => !!id) }
  async function persistResources(conversation: ChatConversation, next = { skills: skillIds, manualKnowledge: manualKnowledgeIds, selectedModel: model }, rows = catalog) {
    const kbIds = effectiveKnowledgeIds(next.skills, next.manualKnowledge, rows).map(serverId).filter((id): id is number => !!id)
    const saved = await saveChatResources(conversation.id, { skills: skillNumbers(next.skills), knowledgeBases: kbIds, model: next.selectedModel }); patchSession(saved)
    storeManualKnowledge(saved.id, next.manualKnowledge.filter(id => saved.knowledgeBases.map(String).includes(id)))
    return saved
  }
  async function changeResources(change: { skills?: string[]; manualKnowledge?: string[]; selectedModel?: string | null }, strict = false, rows = catalog) {
    const next = { skills: change.skills ?? skillIds, manualKnowledge: change.manualKnowledge ?? manualKnowledgeIds, selectedModel: change.selectedModel === undefined ? model : change.selectedModel }
    if (!active) { setSkillIds(next.skills); setManualKnowledgeIds(next.manualKnowledge); setModel(next.selectedModel); return }
    try {
      const saved = await persistResources(active, next, rows)
      const savedKnowledgeIds = saved.knowledgeBases.map(String)
      setSkillIds(saved.skills.map(String)); setManualKnowledgeIds(next.manualKnowledge.filter(id => savedKnowledgeIds.includes(id))); setModel(saved.model)
    }
    catch (reason) { setError((reason as Error).message); if (strict) throw reason }
  }
  async function clearSession() {
    if (!active || busy) return
    try { const saved = await clearChatConversation(active.id); patchSession(saved); setMessages(current => ({ ...current, [active.id]: [] })); setError(''); setNotice('已清空当前会话') } catch (reason) { setError((reason as Error).message) }
  }
  async function removeSession(conversationId: string) {
    try { await deleteChatConversation(conversationId); removeStoredManualKnowledge(conversationId); const rest = sessions.filter(row => row.id !== conversationId); setSessions(rest); setMessages(current => { const next = { ...current }; delete next[conversationId]; return next }); if (conversationId === activeId) { setActiveId(''); setSkillIds([]); setManualKnowledgeIds([]); setModel(null); if (rest[0]) void loadConversation(rest[0].id) } } catch (reason) { setError((reason as Error).message); throw reason }
  }
  async function toggleFavorite(conversation: ChatConversation) { try { patchSession(await favoriteChatConversation(conversation.id, !conversation.favorite)) } catch (reason) { setError((reason as Error).message) } }
  function addFiles(incoming: File[]) { const existing = files.map((file, index) => ({ id: String(index), name: file.name, size: file.size, lastModified: file.lastModified })); const result = validateResourceFiles(incoming, existing, chatFileExtensions, chatFileLimits); setFiles(previous => [...previous, ...result.accepted]); setError(result.errors.join('；')); return result }
  function addPastedImages(items: DataTransferItemList | null) {
    const suffixByMime: Record<string, string> = { 'image/png': '.png', 'image/jpeg': '.jpg' }
    const now = Date.now()
    const images = Array.from(items ?? []).flatMap((item, index) => {
      const suffix = suffixByMime[item.type]
      const file = suffix ? item.getAsFile() : null
      return file ? [new File([file], `粘贴图片-${now}-${index + 1}${suffix}`, { type: file.type, lastModified: now })] : []
    })
    if (!images.length) return false
    const result = addFiles(images)
    if (result.accepted.length) setNotice(`已添加 ${result.accepted.length} 张粘贴图片`)
    return true
  }
  function setTaskProgress(progress: number) {
    document.querySelectorAll<HTMLElement>('.assistant-float .aip-message.generating .aip-progress').forEach(node => {
      node.style.setProperty('--aip-progress-width', `${progress}%`)
      node.dataset.progress = `${progress}%`
    })
  }
  function applyTask(conversationId: string, messageId: string, current: ChatTask) {
    const apply = () => updateMessage(conversationId, messageId, message => ({ ...message, text: current.content || (current.status === 'failed' ? current.error || '生成失败，请稍后重试。' : message.text), status: statusOf(current), artifacts: current.artifacts, taskId: current.taskId, serverId: current.messageId }))
    if (current.status === 'success') {
      setTaskProgress(100)
      window.setTimeout(apply, 220)
      return
    }
    apply()
  }
  async function followTask(running: ActiveTask) {
    try { await streamChatTask(running.taskId, result => applyTask(running.conversationId, String(running.messageId), result), running.controller.signal) }
    catch (reason) { if (!running.controller.signal.aborted) { const message = (reason as Error).message || '生成失败，请稍后重试。'; updateMessage(running.conversationId, String(running.messageId), item => ({ ...item, status: 'failed', text: message })); setError(message) } }
    finally { setRunningTasks(current => { const next = { ...current }; delete next[running.taskId]; return next }) }
  }
  async function send(prompt = text, selectedFiles = files) {
    if (busy || loading || (!prompt.trim() && !selectedFiles.length)) return
    setError('')
    try {
      const conversation = await ensureConversation(prompt); const saved = await persistResources(conversation)
      const context = useAssistantContextStore.getState().object
      const sent = await sendChatMessage(saved.id, prompt, saved.model, selectedFiles, context?.module === contextModule ? { ...context } : { module: contextModule }, resendSource)
      const user: ChatMessage = { id: `local-${Date.now()}`, role: 'user', taskId: sent.taskId, text: prompt.trim() || '请结合本次上传文件协助分析。', attachments: selectedFiles.map(file => file.name) }
      const assistant: ChatMessage = { id: String(sent.messageId), serverId: sent.messageId, taskId: sent.taskId, role: 'assistant', text: '', status: 'generating' }
      updateMessages(saved.id, rows => [...rows, user, assistant]); setFiles([]); setText(''); setResendSource(undefined)
      const running = { taskId: sent.taskId, conversationId: saved.id, messageId: sent.messageId, controller: new AbortController() }; setRunningTasks(current => ({ ...current, [running.taskId]: running })); void followTask(running)
    } catch (reason) { setError((reason as Error).message) }
  }
  async function stop() { const current = task || taskRows.find(item => item.conversationId === activeId && ['pending', 'running', 'cancelling', 'recovering'].includes(item.status)); if (!current) return; try { applyTask(current.conversationId, String(current.messageId), await stopChatTask(current.taskId)); setNotice('已请求停止，正在等待服务端结束任务。') } catch (reason) { setError((reason as Error).message) } }
  async function retry(message: ChatMessage, replacementFiles: File[] = []) {
    if (busy || !message.taskId || !active) return
    try {
      const sent = await retryChatTask(message.taskId, replacementFiles)
      updateMessages(active.id, rows => [...rows, { id: String(sent.messageId), serverId: sent.messageId, taskId: sent.taskId, role: 'assistant', text: '', status: 'generating' }])
      const running = { taskId: sent.taskId, conversationId: active.id, messageId: sent.messageId, controller: new AbortController() }
      setRunningTasks(current => ({ ...current, [running.taskId]: running })); void followTask(running)
    } catch (reason) { setError((reason as Error).message) }
  }
  async function feedback(message: ChatMessage, rating: 'up' | 'down', reason?: string) {
    if (!message.serverId) return
    await sendChatFeedback(message.serverId, rating === 'up' ? 'like' : 'dislike', reason)
    updateMessage(activeId, message.id, item => ({ ...item, feedback: rating, feedbackReason: reason })); setNotice('感谢反馈')
  }
  function resend(message: ChatMessage) {
    setText(message.text); setFiles([]); setResendSource(message.taskId)
    setNotice(message.attachments?.length ? '已取回原输入，请重新上传或替换附件后发送。' : '已取回原输入，修改后发送将创建新消息。')
  }
  async function copy(textToCopy: string) { setNotice(await copyText(textToCopy) ? '已复制到剪贴板' : '浏览器未授予剪贴板权限') }
  function startDrag(event: ReactPointerEvent<HTMLElement>) {
    const target = event.target as Element
    if (maximized || !target.closest('.aip-header') || target.closest('button, input, textarea, label, select, .aip-messages, .aip-composer, .aip-session-drawer')) return
    event.preventDefault()
    drag.current = { x: event.clientX, y: event.clientY, offsetX: offset.x, offsetY: offset.y, source: 'panel', bounds: event.currentTarget.getBoundingClientRect() }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  function startTriggerDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    triggerDragged.current = false
    drag.current = { x: event.clientX, y: event.clientY, offsetX: offset.x, offsetY: offset.y, source: 'trigger', bounds: event.currentTarget.getBoundingClientRect() }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  function toggleTrigger() { if (triggerDragged.current) { triggerDragged.current = false; return } if (open) close(); else void openPanel() }

  return <>
    {createPortal(<div className={`assistant-float ${maximized ? 'maxed' : ''}`} style={!maximized && (offset.x || offset.y) ? { transform: `translate(${offset.x}px, ${offset.y}px)` } : undefined}>
      <button ref={trigger} className={`assistant-trigger ${open ? 'is-open' : ''}`} data-state={state} aria-label={open ? '收起智能助手' : '打开智能助手'} aria-expanded={open} onPointerDown={startTriggerDrag} onClick={toggleTrigger}><span className="assistant-ring" /><span className="aip-orb-bot" aria-hidden="true"><svg viewBox="0 0 100 100" width="46" height="46"><path d="M31 26Q21 8 39 12Q33 18 37 28Z" fill="#fbfdfd" stroke="#d5e0dd" strokeWidth="1.5" /><path d="M69 26Q79 8 61 12Q67 18 63 28Z" fill="#fbfdfd" stroke="#d5e0dd" strokeWidth="1.5" /><ellipse cx="50" cy="55" rx="42" ry="39" fill="#f1f5f3" stroke="#d5e0dd" strokeWidth="1.5" /><path d="M11 62Q50 84 89 62Q84 88 50 91Q16 88 11 62Z" fill="#dde7e4" /><rect x="26" y="38" width="48" height="34" rx="16" fill="#22434b" /><rect className="aip-eye" x="39.5" y="45" width="9.5" height="20" rx="4.7" fill="#fff" /><rect className="aip-eye" x="51" y="45" width="9.5" height="20" rx="4.7" fill="#fff" /></svg></span><span className="aip-orb-close" aria-hidden="true"><X size={25} /></span>{!!unread && <span className="assistant-badge">{unread > 99 ? '99+' : unread}</span>}<span className="assistant-tip"><b>{busy ? '正在生成' : unread ? `${unread} 条新回复` : 'AI 助手'}</b><i>{busy ? '可转入后台继续处理' : '全局可用'}</i></span></button>
      {open && <aside className={`assistant-panel aip-panel ${maximized ? 'aip-maximized' : ''}`} role="dialog" aria-label="平台级 AI 助手" aria-modal="false" style={!maximized ? { width: geometry.size.width, height: Math.min(geometry.size.height, window.innerHeight - 104) } : undefined} data-page-context={contextLabel} onPointerDown={startDrag}>
        <header className="aip-header"><span className="aip-avatar"><span className="aip-avatar-face">AI</span></span><div className="aip-brand"><div className="aip-title">平台级 AI 助手 <span>全局</span></div><div className="aip-sub"><i />{busy ? '正在生成回复…' : loading ? '正在加载服务端会话…' : '已连接对话服务'}</div></div><div className="aip-head-actions"><button aria-label="后台任务" onClick={() => setTaskListOpen(true)}><ListTodo size={15} /></button><button aria-label="偏好设置" onClick={() => setPreferences(true)}><Settings size={15} /></button><button className={drawer ? 'on' : ''} aria-label="查看会话" title="会话" onPointerDown={event => event.stopPropagation()} onClick={() => setDrawer(value => !value)}><History size={15} />{unread > 0 && <i className="aip-unread-dot" />}</button><button aria-label="新建会话" title="新建会话" disabled={loading} onPointerDown={event => event.stopPropagation()} onClick={() => void newSession()}><MessageSquarePlus size={15} /></button><button aria-label={maximized ? '还原窗口' : '最大化窗口'} title={maximized ? '还原窗口' : '最大化窗口'} onPointerDown={event => event.stopPropagation()} onClick={() => setMaximized(value => !value)}>{maximized ? <Minimize2 size={15} /> : <Maximize2 size={15} />}</button><button className="aip-close" aria-label="关闭助手" title="关闭" onPointerDown={event => event.stopPropagation()} onClick={close}><X size={16} /></button></div></header>
        {import.meta.env.VITE_ASSISTANT_ARTIFACT_MOCK === 'true' && <ArtifactDemo />}
        <section className="aip-resources" aria-label="本次会话资源"><div><b>SKILL</b><span>{selectedSkills.length ? selectedSkills.map(skill => <em key={skill.id}><Sparkles size={11} />{skill.name}<button disabled={busy} title="移除 Skill；仅移除它带入的知识库来源" aria-label={`移除 ${skill.name}`} onClick={() => void changeResources({ skills: skillIds.filter(id => id !== skill.id) })}>×</button></em>) : <small>未加载 · 使用通用对话</small>}<button className="aip-add" disabled={busy} onClick={() => setPickingSkills(true)}>+ 加载</button></span></div><div><b>知识库</b><span>{selectedKnowledge.length ? selectedKnowledge.map(item => { const id = String(item.id); const sources = knowledgeSourceMap.get(id) ?? []; const manual = manualKnowledgeIds.includes(id); return <em key={id} className={sources.length ? 'context' : ''} title={sources.length ? `由 Skill 自动挂载：${sources.join('、')}` : '手动挂载'}><Check size={11} />{item.name}{sources.length ? <i className="aip-resource-origin">来自 {sources.join('、')}</i> : manual ? <i className="aip-resource-origin">手动</i> : null}{!sources.length && manual && <button disabled={busy} aria-label={`移除 ${item.name}`} onClick={() => void changeResources({ manualKnowledge: manualKnowledgeIds.filter(knowledgeId => knowledgeId !== id) })}>×</button>}</em> }) : <small>未挂载</small>}<button className="aip-add" disabled={busy} onClick={() => setPickingKnowledge(true)}>+ 挂载</button></span></div></section>
        <div className="aip-messages" role="log" aria-live="polite">{loading && !active ? <p className="aip-working"><LoaderCircle size={13} className="spin" />正在加载会话记录…</p> : !activeMessages.length && <section className="aip-welcome"><h3>你好，我是平台级 AI 入口</h3><p>消息、会话、已选资源和模型均保存到后端；可加载已上线 Skill 后发起真实任务。</p><div>{suggestions.map(([tag, value]) => <button key={tag} onClick={() => setText(value)}><span>{tag}</span>{value}</button>)}</div></section>}{activeMessages.map(message => message.role === 'user' ? <article className="aip-message user" key={message.id}><p>{message.text}</p><footer><button className="aip-action" onClick={() => void copy(message.text)}>复制</button><button className="aip-action" disabled={busy} onClick={() => resend(message)}>修改后重发</button></footer>{message.attachments?.length ? <div className="aip-message-meta">{message.attachments.map(name => <span key={name}><Paperclip size={11} />{name}</span>)}</div> : null}</article> : <article className={`aip-message bot ${message.status ?? 'completed'}`} key={message.id}>{message.status === 'generating' ? <><header><Sparkles size={14} /><b>对话服务 · 生成中</b><span>流式返回</span></header><div className="aip-progress"><i /></div>{message.text ? <p>{message.text}</p> : <p className="aip-working"><LoaderCircle size={13} className="spin" />正在调用后端模型…</p>}<footer>{task?.taskId === message.taskId && <button className="aip-action danger" onClick={() => void stop()}><Square size={12} />停止生成</button>}<button className="aip-action ghost" onClick={close}>转入后台</button></footer></> : <><header>{message.status === 'failed' ? <X size={14} /> : message.status === 'stopped' ? <Square size={13} /> : <Check size={14} />}<b>{message.status === 'failed' ? '生成失败' : message.status === 'stopped' ? '已停止生成' : 'AI 助手'}</b><span>{message.status === 'completed' ? '已完成' : ''}</span></header><p>{message.text}</p>{!!message.artifacts?.length && <div className="aip-message-meta">{message.artifacts.map(artifact => <button type="button" className="aip-action" key={artifact.artifactId} onClick={() => setSelectedArtifactId(artifact.artifactId)}><FileText size={14} />查看产出物：{artifact.fileName}</button>)}</div>}<footer><button className="aip-action" onClick={() => void copy(message.text)}><Copy size={12} />复制</button>{message.taskId && <><label className="aip-action">替换附件重试<input type="file" multiple hidden accept={chatFileExtensions.join(',')} disabled={busy} onChange={event => { const incoming = Array.from(event.target.files ?? []); const checked = validateResourceFiles(incoming, [], chatFileExtensions, chatFileLimits); if (checked.errors.length) setError(checked.errors.join('；')); else if (checked.accepted.length) void retry(message, checked.accepted); event.target.value = '' }} /></label><button className="aip-action" disabled={busy} onClick={() => void retry(message)}><RotateCcw size={12} />重新生成</button></>}{message.status === 'completed' && <span className="aip-feedback"><button className={message.feedback === 'up' ? 'selected up' : ''} aria-label="有帮助" onClick={() => void feedback(message, 'up').catch(reason => setError((reason as Error).message))}><ThumbsUp size={13} /></button><button className={message.feedback === 'down' ? 'selected down' : ''} aria-label="需改进" onClick={() => setFeedbackTarget(message)}><ThumbsDown size={13} /></button></span>}</footer></>}</article>)}<div ref={bottom} /></div>
        <section className="aip-composer"><button className="aip-action" disabled={busy || !active} onClick={() => setConfirmClear(true)}>清空当前会话</button>{resendSource && <p className="helper-text">正在修改原请求；发送后保留原消息。<button onClick={() => setResendSource(undefined)}>取消重发</button></p>}<div className="aip-attachments">{files.map((file, index) => <span key={`${file.name}-${index}`}><Paperclip size={11} />{file.name}<button disabled={busy} aria-label={`移除 ${file.name}`} onClick={() => setFiles(current => current.filter((_, fileIndex) => fileIndex !== index))}>×</button></span>)}</div><div className="aip-input"><textarea aria-label="向智能助手提问" placeholder="描述你的诉求，Enter 发送，Shift + Enter 换行" maxLength={40000} value={text} disabled={busy || loading} onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} /><div><label className={busy ? 'disabled' : ''}><Paperclip size={16} /><input type="file" multiple accept={chatFileExtensions.join(',')} disabled={busy} aria-label="上传本次对话文件" onChange={event => { addFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} /></label><small>单文件 ≤ 20 MB，最多 10 个</small><span className="aip-model-picker"><button className={`aip-model ${modelOpen ? 'on' : ''}`} type="button" aria-label="选择对话模型" aria-haspopup="dialog" aria-expanded={modelOpen} disabled={busy} onClick={() => setModelOpen(value => !value)}><Sparkles size={12} /><span>{modelLabel}</span><ChevronDown size={12} /></button>{modelOpen && <span className="aip-model-pop" role="dialog" aria-label="模型选择"><b>模型 · 能力与成本的权衡</b><button className={!model ? 'selected' : ''} onClick={() => { setModelOpen(false); void changeResources({ selectedModel: null }) }}><span><strong>自动 <em>推荐</em></strong><small>按诉求复杂度、已加载 Skill 和知识库自动选择健康模型</small></span>{!model && <Check size={16} />}</button>{models.map(item => <button key={item.name} className={model === item.name ? 'selected' : ''} disabled={['unavailable', 'unconfigured'].includes(healthFor(item.name)?.status ?? '')} onClick={() => { setModelOpen(false); void changeResources({ selectedModel: item.name }) }}><span><strong>{item.displayName}<em className={`model-tier ${healthFor(item.name)?.status ?? 'checking'}`}>{modelTier(item.name)}</em></strong><small>{modelDescription(item.name)}</small></span>{model === item.name && <Check size={16} />}</button>)}<i>健康状态由后端实时检测；自动分配会在结果中标注实际使用的模型</i></span>}</span>{busy ? <button className="aip-stop" onClick={() => void stop()}><Square size={12} />停止</button> : <button className="aip-send" disabled={loading || (!text.trim() && !files.length)} onClick={() => void send()}><Send size={13} />发送</button>}</div></div>{error && <p className="aip-error" role="alert">{error}</p>}</section>
        {drawer && <AssistantSessions sessions={sessions} activeId={activeId} onClose={() => setDrawer(false)} onSelect={id => { setDrawer(false); void loadConversation(id) }}
          onNew={() => void newSession()} onFavorite={item => void toggleFavorite(item)} onDelete={removeSession} onRenamed={patchSession}
          onClearAll={async () => { await deleteAllChatConversations(); sessions.forEach(item => removeStoredManualKnowledge(item.id)); setSessions([]); setMessages({}); setActiveId(''); setSkillIds([]); setManualKnowledgeIds([]) }} />}
        {!maximized && <button className="aip-resize-handle" aria-label="调整助手尺寸" onPointerDown={event => { event.preventDefault(); event.stopPropagation(); resize.current = { x: event.clientX, y: event.clientY, ...geometry.size }; event.currentTarget.setPointerCapture(event.pointerId) }}>↖</button>}

      </aside>}
    </div>, portalTarget || document.body)}
    {feedbackTarget && <AssistantFeedback onClose={() => setFeedbackTarget(undefined)} onSave={reason => feedback(feedbackTarget, 'down', reason)} />}
    {preferences && <Dialog className="assistant-owned-dialog" title="偏好设置" onClose={() => setPreferences(false)} footer={<button className="button" onClick={() => setPreferences(false)}>关闭</button>}>
      <label><input type="checkbox" checked={geometry.remember} onChange={event => setGeometry(value => ({ ...value, remember: event.target.checked }))} />记忆位置与尺寸</label>
      <label><input type="checkbox" checked={geometry.degrade} onChange={event => setGeometry(value => ({ ...value, degrade: event.target.checked }))} />弹窗场景自动收起</label>
      <button className="button" onClick={resetGeometry}>恢复默认位置与尺寸</button></Dialog>}
    {taskListOpen && <Dialog className="assistant-owned-dialog" title="后台任务" onClose={() => setTaskListOpen(false)} footer={<button className="button" onClick={() => setTaskListOpen(false)}>关闭</button>}>
      <div className="assistant-skill-results">{taskRows.map(row => <article key={row.taskId}><div><h3>{sessions.find(item => item.id === row.conversationId)?.title || '会话任务'}</h3><p>任务 {row.taskId} · {{ pending: '等待调度', running: '模型执行中', cancelling: '正在停止', recovering: '恢复中', success: '已完成', failed: '失败', cancelled: '已停止' }[row.status]}</p>{row.error && <p>{row.error}</p>}</div>
        <button className="button small" onClick={() => { setTaskListOpen(false); setOpen(true); void loadConversation(row.conversationId) }}>查看</button></article>)}{!taskRows.length && <p>暂无后台任务</p>}</div></Dialog>}
    {confirmClear && <Dialog className="assistant-owned-dialog" title="清空当前会话" onClose={() => setConfirmClear(false)} footer={<><button className="button" onClick={() => setConfirmClear(false)}>取消</button><button className="button primary" onClick={() => { setConfirmClear(false); void clearSession() }}>确认清空</button></>}><p>将清空当前会话及临时产出物，正式资产不受影响。</p></Dialog>}
    {selectedArtifactId && <ArtifactWorkbench key={selectedArtifactId} artifactId={selectedArtifactId} onClose={() => setSelectedArtifactId(undefined)} />}
    {notice && <div className="aip-toast" role="status">{notice}</div>}
    {pickingSkills && <AssistantResourcePicker kind="skills" selected={skillIds} busy={busy} onClose={() => setPickingSkills(false)}
      onSkill={async item => { const skill = await getCatalogSkill(item.id); const nextCatalog = [...catalog.filter(row => row.id !== skill.id), skill]; setCatalog(nextCatalog); await changeResources({ skills: [...skillIds, skill.id] }, true, nextCatalog) }} onKnowledge={async () => {}} />}
    {pickingKnowledge && <AssistantResourcePicker kind="knowledge" selected={knowledgeIds} busy={busy} onClose={() => setPickingKnowledge(false)}
      onKnowledge={async item => { setKnowledgeBases(rows => [...rows.filter(row => row.id !== item.id), item]); await changeResources({ manualKnowledge: [...manualKnowledgeIds, item.id] }, true) }} onSkill={async () => {}} />}

  </>
}
