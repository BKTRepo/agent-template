import { useEffect, useRef, useCallback, useState } from 'react'
import { ArrowDown, MessagesSquare, PanelLeft } from 'lucide-react'
import { Button } from '@heroui/react'
import { toast } from '@/lib/toast'
import { useChatStore } from '@/stores/chatStore'
import { useSettingsStore } from '@/stores/settingsStore'
import { useConversationStore } from '@/stores/conversationStore'
import { ConversationSidebar } from '@/components/chat/ConversationSidebar'
import { ChatMessage } from '@/components/chat/ChatMessage'
import { ChatComposer } from '@/components/chat/ChatComposer'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ChatSettingsDialog } from '@/components/chat/ChatSettingsDialog'
import { sendQuery, sendQueryStream, resumeQueryStream } from '@/api/query'
import { getAnswerFeedback, getConversationMessages, setAnswerFeedback, stopMessageGeneration } from '@/api/conversations'
import { cn } from '@/lib/utils'
import { copyText } from '@/lib/clipboard'

/** 流式增量刷新间隔: 缓冲的文本按此节拍均匀吐出, 避免一段一段蹦字 */
const FLUSH_INTERVAL_MS = 30

export default function ChatPage() {
  const messages = useChatStore.use.messages()
  const isStreaming = useChatStore.use.isStreaming()
  const conversationHistory = useChatStore.use.conversationHistory()
  const addUserMessage = useChatStore.use.addUserMessage()
  const addAssistantMessage = useChatStore.use.addAssistantMessage()
  const appendContent = useChatStore.use.appendContent()
  const setReferences = useChatStore.use.setReferences()
  const setRetrievalDetail = useChatStore.use.setRetrievalDetail()
  const finalizeStreaming = useChatStore.use.finalizeStreaming()
  const markInterrupted = useChatStore.use.markInterrupted()
  const resetForResume = useChatStore.use.resetForResume()
  const setServerIndices = useChatStore.use.setServerIndices()
  const setThinkingMs = useChatStore.use.setThinkingMs()
  const setStreaming = useChatStore.use.setStreaming()
  const setAbortController = useChatStore.use.setAbortController()
  const stopStreaming = useChatStore.use.stopStreaming()
  const replaceAssistantMessage = useChatStore.use.replaceAssistantMessage()
  const scrollTarget = useChatStore.use.scrollTarget()
  const setScrollTarget = useChatStore.use.setScrollTarget()

  const currentId = useConversationStore.use.currentId()
  const ensureCurrent = useConversationStore.use.ensureCurrent()
  const loadConversations = useConversationStore.use.loadConversations()
  const loadingMessages = useConversationStore.use.loadingMessages()

  const chatMode = useSettingsStore.use.chatMode()
  const llmModel = useSettingsStore.use.llmModel()
  const naiveTopK = useSettingsStore.use.naiveTopK()
  const rrfTopK = useSettingsStore.use.rrfTopK()
  const denseTopK = useSettingsStore.use.denseTopK()
  const bm25TopK = useSettingsStore.use.bm25TopK()
  const responseType = useSettingsStore.use.responseType()
  const enableRerank = useSettingsStore.use.enableRerank()
  const includeRefs = useSettingsStore.use.includeRefs()
  const streamEnabled = useSettingsStore.use.streamEnabled()
  const temperature = useSettingsStore.use.temperature()

  const [input, setInput] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const shouldFollowRef = useRef(true)
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)
  /** 滚动区是否贴顶: 与 atBottom 一起驱动顶/底渐隐覆盖层的显隐 */
  const [atTop, setAtTop] = useState(true)
  /** 搜索跳转后短暂高亮的消息下标 */
  const [highlightIndex, setHighlightIndex] = useState<number | null>(null)
  const highlightTimerRef = useRef<number | null>(null)
  const [feedbackByIndex, setFeedbackByIndex] = useState<Record<number, 'accepted' | 'revoked' | null>>({})
  const feedbackKey = messages
    .filter((message) => message.role === 'assistant' && message.serverIndex != null)
    .map((message) => `${message.serverIndex}`)
    .join('|')

  // ---- 流式平滑缓冲: SSE 片段先入缓冲, 定时器按节拍均匀追加到消息 ----
  const bufRef = useRef('')
  const flushTimerRef = useRef<number | null>(null)

  const flushNow = useCallback((msgId?: string) => {
    if (bufRef.current) {
      const chunk = bufRef.current
      bufRef.current = ''
      appendContent(chunk, msgId)
    }
  }, [appendContent])

  const startFlusher = useCallback((msgId?: string) => {
    if (flushTimerRef.current != null) return
    flushTimerRef.current = window.setInterval(() => flushNow(msgId), FLUSH_INTERVAL_MS)
  }, [flushNow])

  const stopFlusher = useCallback((msgId?: string) => {
    if (flushTimerRef.current != null) {
      window.clearInterval(flushTimerRef.current)
      flushTimerRef.current = null
    }
    flushNow(msgId)
  }, [flushNow])

  useEffect(() => () => {
    if (flushTimerRef.current != null) window.clearInterval(flushTimerRef.current)
  }, [])

  // 自动跟随滚动: 只在内容实际变化时触发（轮询重建数组但内容未变时不滚动,
  // 避免生成中轮询导致的重复滚动抖动）
  const contentFingerprint = messages.reduce((n, m) => n + m.content.length, 0) + messages.length
  useEffect(() => {
    if (shouldFollowRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    } else {
      // 非跟随态下内容变化（如切换会话载入历史）不产生真实 scroll 事件,
      // 直接按当前几何刷新跟随标记与顶/底渐隐状态;
      // 跟随态由 scrollIntoView 产生的真实滚动事件覆盖
      const el = scrollAreaRef.current
      if (el) {
        const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60
        shouldFollowRef.current = nearBottom
        setAtTop(el.scrollTop <= 2)
        setAtBottom(nearBottom)
      }
    }
  }, [contentFingerprint])

  useEffect(() => {
    loadConversations().catch(() => {})
  }, [loadConversations])

  // 会话载入后读取服务端反馈状态，确保刷新或重新打开会话时按钮状态一致。
  useEffect(() => {
    setFeedbackByIndex({})
    if (currentId == null || !feedbackKey) return
    const indexes = feedbackKey.split('|').map(Number)
    let cancelled = false
    Promise.all(indexes.map(async (index) => {
      try {
        return await getAnswerFeedback(currentId, index)
      } catch {
        return null
      }
    })).then((statuses) => {
      if (cancelled) return
      const next: Record<number, 'accepted' | 'revoked' | null> = {}
      statuses.forEach((status, i) => {
        if (status) next[indexes[i]] = status.effective ? 'accepted' : null
      })
      setFeedbackByIndex(next)
    })
    return () => { cancelled = true }
  }, [currentId, feedbackKey])

  const handleChatScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60
    shouldFollowRef.current = nearBottom
    setAtTop(el.scrollTop <= 2)
    setAtBottom(nearBottom)
  }

  const scrollToBottom = useCallback(() => {
    shouldFollowRef.current = true
    setAtBottom(true)
    scrollAreaRef.current?.scrollTo({ top: scrollAreaRef.current.scrollHeight, behavior: 'smooth' })
  }, [])

  /** 发起提问/重新生成时瞬时贴底并恢复跟随。
    刻意不用 smooth 动画: 用户上滑浏览历史时跟随标记已被 scroll 事件置 false,
    长动画途中 scroll 事件同样会把标记打回 false——此时流式内容到达会让
    跟随彻底丢失。瞬时跳转一次到底, 新消息渲染后跟随 effect 的 smooth
    scrollIntoView 只补一小段增量, 既贴底又无丢跟随风险。 */
  const jumpToBottomOnSend = useCallback(() => {
    shouldFollowRef.current = true
    setAtBottom(true)
    const el = scrollAreaRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  const buildPayload = useCallback((query: string, history: { role: string; content: string }[], conversationId: number | null, replaceIndex: number | null = null) => ({
    query,
    mode: chatMode,
    model: llmModel,
    response_type: responseType,
    chunk_top_k: naiveTopK,
    rrf_top_k: rrfTopK,
    conversation_history: history,
    conversation_id: conversationId,
    ...(replaceIndex != null ? { replace_message_index: replaceIndex } : {}),
    enable_rerank: enableRerank,
    include_references: includeRefs,
    dense_top_k: denseTopK,
    bm25_top_k: bm25TopK,
    temperature,
  }), [chatMode, llmModel, responseType, naiveTopK, rrfTopK, enableRerank, includeRefs, denseTopK, bm25TopK, temperature])

  /** 读取 SSE 流并把事件分发到 store; 记录首字耗时(思考时间)。
   *  返回 failed=是否收到 error 事件; noActiveStream=重连时服务端已无在途任务。 */
  const consumeStream = useCallback(async (
    resp: Response,
    msgId?: string,
  ): Promise<{ failed: boolean; noActiveStream: boolean }> => {
    if (!resp.ok) throw new Error(`Server error ${resp.status}`)
    const reader = resp.body?.getReader()
    if (!reader) throw new Error('No response body')
    const decoder = new TextDecoder()
    let buffer = ''
    let streamFailed = false
    let noActiveStream = false
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6).trim()
        if (payload === '[DONE]') break
        try {
          const evt = JSON.parse(payload)
          if (evt.type === 'retrieval') {
            setRetrievalDetail({
              rewritten_query: evt.rewritten_query ?? null,
              query_mode: evt.query_mode ?? 'hybrid',
              total_found: evt.total_found ?? 0,
              final_count: evt.final_count ?? 0,
              chunks: evt.chunks ?? [],
            }, msgId)
          } else if (evt.type === 'references') setReferences(evt.references || [], msgId)
          else if (evt.type === 'content') {
            bufRef.current += evt.content || ''
            startFlusher(msgId)
          } else if (evt.type === 'persisted') setServerIndices(evt.user_index ?? null, evt.assistant_index ?? null)
          else if (evt.type === 'no_active_stream') noActiveStream = true
          else if (evt.type === 'done') {
            // done 携带服务端落盘的思考耗时: 覆盖本地测量, 重连重建的消息也有值
            if (typeof evt.thinking_ms === 'number') setThinkingMs(evt.thinking_ms, msgId)
          }
          else if (evt.type === 'error') {
            streamFailed = true
            stopFlusher(msgId)
            markInterrupted(msgId)
            toast.danger(evt.content || '生成失败')
          }
        } catch {
          /* skip malformed */
        }
      }
    }
    return { failed: streamFailed, noActiveStream }
  }, [setRetrievalDetail, setReferences, setServerIndices, setThinkingMs, markInterrupted, startFlusher, stopFlusher])

  const handleSend = useCallback(async () => {
    const q = input.trim()
    if (!q || isStreaming || useChatStore.getState().messages.some((m) => m.status === 'generating')) return
    setInput('')
    addUserMessage(q)
    // 发送即贴底: 无论此前停在哪个位置, 新问题与流式回答都从底部开始跟随
    jumpToBottomOnSend()
    setStreaming(true)

    let conversationId: number | null = null
    try {
      conversationId = await ensureCurrent()
    } catch {
      conversationId = null
    }

    const t0 = performance.now()
    if (streamEnabled) {
      const ctrl = new AbortController()
      setAbortController(ctrl)
      const id = addAssistantMessage()
      let timed = false
      // 思考计时: 轮询缓冲, 首个正文片段到达缓冲的时刻即"首字返回"
      const firstTokenTimer = window.setInterval(() => {
        if (!timed && bufRef.current) {
          timed = true
          setThinkingMs(performance.now() - t0, id)
        }
      }, 16)
      try {
        const resp = await sendQueryStream(buildPayload(q, [...conversationHistory], conversationId), ctrl.signal)
        const { failed: streamFailed } = await consumeStream(resp, id)
        stopFlusher(id)
        if (!streamFailed) {
          if (!timed) setThinkingMs(performance.now() - t0, id)
          finalizeStreaming(id)
        }
      } catch (err) {
        stopFlusher(id)
        if ((err as Error).name === 'AbortError') return
        toast.danger(`请求失败: ${err instanceof Error ? err.message : String(err)}`)
        markInterrupted(id)
      } finally {
        window.clearInterval(firstTokenTimer)
      }
    } else {
      addAssistantMessage()
      try {
        const resp = await sendQuery(buildPayload(q, [...conversationHistory], conversationId))
        setThinkingMs(performance.now() - t0)
        appendContent(resp.response || '无响应')
        if (resp.references) setReferences(resp.references)
        if (resp.retrieval) setRetrievalDetail(resp.retrieval)
        setServerIndices(resp.user_message_index ?? null, resp.message_index ?? null)
        finalizeStreaming()
      } catch {
        toast.danger('请求失败')
        markInterrupted()
      }
    }
    setStreaming(false)
    setAbortController(null)
    loadConversations().catch(() => {})
    setTimeout(() => inputRef.current?.focus(), 100)
  }, [input, isStreaming, streamEnabled, conversationHistory, ensureCurrent, loadConversations, buildPayload, consumeStream, addAssistantMessage, addUserMessage, jumpToBottomOnSend, setStreaming, setAbortController, setThinkingMs, appendContent, setReferences, setRetrievalDetail, setServerIndices, finalizeStreaming, markInterrupted])

  const handleRegenerate = useCallback(async (aiMsgId: string) => {
    if (isStreaming) return
    const idx = messages.findIndex((m) => m.id === aiMsgId)
    if (idx <= 0) return
    const userMsg = messages[idx - 1]
    if (userMsg.role !== 'user') return
    const question = userMsg.content
    const targetMsg = messages[idx]
    const persistedConvId = targetMsg?.serverIndex != null ? currentId : null
    const replaceIndex = targetMsg?.serverIndex ?? null
    const newId = replaceAssistantMessage(aiMsgId)
    jumpToBottomOnSend()
    setStreaming(true)

    // 历史只取本轮之前: 不含目标问题（它作为 query 单独发送, 避免重复入提示词）,
    // 也不含被重新生成的旧回答; 未完成(interrupted/generating)的回答不入上下文
    const history = messages
      .slice(0, idx - 1)
      .filter((m) => m.role === 'user' || m.status === 'done')
      .map((m) => ({ role: m.role, content: m.content }))

    // 点击时刻的配置快照: 检索模式/模型/各模式参数/流式开关, 避免闭包取到旧值
    const s = useSettingsStore.getState()
    const payload = {
      query: question,
      mode: s.chatMode,
      model: s.llmModel,
      response_type: s.responseType,
      chunk_top_k: s.naiveTopK,
      rrf_top_k: s.rrfTopK,
      conversation_history: history,
      conversation_id: persistedConvId,
      ...(replaceIndex != null ? { replace_message_index: replaceIndex } : {}),
      enable_rerank: s.enableRerank,
      include_references: s.includeRefs,
      dense_top_k: s.denseTopK,
      bm25_top_k: s.bm25TopK,
      temperature: s.temperature,
    }

    const t0 = performance.now()
    if (s.streamEnabled) {
      const ctrl = new AbortController()
      setAbortController(ctrl)
      let timed = false
      try {
        const resp = await sendQueryStream(payload, ctrl.signal)
        const timer = window.setInterval(() => {
          if (!timed && bufRef.current) {
            timed = true
            setThinkingMs(performance.now() - t0, newId)
            window.clearInterval(timer)
          }
        }, 16)
        let streamFailed = false
        try {
          streamFailed = (await consumeStream(resp, newId)).failed
        } finally {
          window.clearInterval(timer)
        }
        stopFlusher(newId)
        if (!streamFailed) {
          if (!timed) setThinkingMs(performance.now() - t0, newId)
          finalizeStreaming(newId)
        }
      } catch (err) {
        stopFlusher(newId)
        if ((err as Error).name === 'AbortError') return
        toast.danger(`请求失败: ${err instanceof Error ? err.message : String(err)}`)
        markInterrupted(newId)
      }
    } else {
      try {
        const resp = await sendQuery(payload)
        setThinkingMs(performance.now() - t0, newId)
        appendContent(resp.response || '无响应', newId)
        if (resp.references) setReferences(resp.references)
        if (resp.retrieval) setRetrievalDetail(resp.retrieval)
        finalizeStreaming(newId)
      } catch {
        toast.danger('请求失败')
        markInterrupted(newId)
      }
    }
    setStreaming(false)
    setAbortController(null)
  }, [isStreaming, messages, currentId, replaceAssistantMessage, jumpToBottomOnSend, setStreaming, setAbortController, consumeStream, setThinkingMs, stopFlusher, appendContent, setReferences, setRetrievalDetail, finalizeStreaming, markInterrupted])

  const handleStop = useCallback(() => {
    const { messages: msgs } = useChatStore.getState()
    const streamingMsg = msgs.find((m) => m.streaming)
    stopFlusher(streamingMsg?.id)
    const convId = useConversationStore.getState().currentId
    if (convId != null && streamingMsg?.serverIndex != null) {
      stopMessageGeneration(convId, streamingMsg.serverIndex).catch(() => {
        /* 服务端兜底超时自愈 */
      })
    }
    stopStreaming()
  }, [stopStreaming, stopFlusher])

  const handleFeedback = useCallback(async (messageIndex: number | null, action: 'accepted' | 'revoked') => {
    if (currentId == null || messageIndex == null) return
    try {
      const status = await setAnswerFeedback(currentId, messageIndex, action)
      setFeedbackByIndex((prev) => ({ ...prev, [messageIndex]: status.effective ? 'accepted' : null }))
      toast.success(action === 'accepted' ? '已采纳该回答' : '已取消采纳')
    } catch (err) {
      toast.danger(err instanceof Error ? err.message : '更新采纳状态失败')
    }
  }, [currentId])

  // 已完成过一次重连尝试的消息（convId:msgId）: no_active_stream / 失败后不再重试同一条,
  // 交由轮询兜底, 避免"重连→无任务→重载→重连"死循环; 新一轮问答 msgId 变化不受影响。
  const resumeAttemptedRef = useRef<string | null>(null)
  const resumeInFlightRef = useRef(false)

  /** 重连: 刷新/切换会话后接回服务端仍在途的生成任务（不重新提问, 模型不会再跑）。
   *  replay 携带本轮全部事件, 因此先清空该消息再从零重建; 服务端无活动任务
   *  （已结束/进程重启）时回退读取持久化数据, 仍生成中则由下方轮询兜底。 */
  const resumeStream = useCallback(async (convId: number, msgId: string, index: number) => {
    const ctrl = new AbortController()
    setAbortController(ctrl)
    setStreaming(true)
    resumeInFlightRef.current = true
    try {
      const resp = await resumeQueryStream(convId, index, ctrl.signal)
      resetForResume(msgId)
      const { failed, noActiveStream } = await consumeStream(resp, msgId)
      stopFlusher(msgId)
      resumeAttemptedRef.current = `${convId}:${msgId}`
      if (noActiveStream) {
        // 任务已不在途: 以持久化数据为准（多数情况下已是终态）;
        // 仅当用户仍停留在该会话时渲染, 避免切换后旧响应覆盖新会话
        const msgs = await getConversationMessages(convId)
        if (useConversationStore.getState().currentId === convId) {
          useChatStore.getState().loadFromHistory(msgs)
        }
        return
      }
      if (!failed) {
        finalizeStreaming(msgId)
        loadConversations().catch(() => {})
      }
    } catch (err) {
      stopFlusher(msgId)
      if ((err as Error).name === 'AbortError') return
      // 重连失败（网络异常等）: 记录已尝试, 回读持久化数据, 仍生成中交由轮询兜底;
      // 同样仅在仍停留该会话时渲染, 避免覆盖已切到的其它会话
      resumeAttemptedRef.current = `${convId}:${msgId}`
      getConversationMessages(convId)
        .then((msgs) => {
          if (useConversationStore.getState().currentId === convId) {
            useChatStore.getState().loadFromHistory(msgs)
          }
        })
        .catch(() => {})
    } finally {
      resumeInFlightRef.current = false
      setStreaming(false)
      setAbortController(null)
    }
  }, [setAbortController, setStreaming, resetForResume, consumeStream, stopFlusher, finalizeStreaming, loadConversations])

  // 切换/刷新进入会话后, 若存在仍在生成的消息, 优先重连在途任务（替代盲目轮询）
  useEffect(() => {
    if (currentId == null) return
    if (useChatStore.getState().isStreaming || resumeInFlightRef.current) return
    const genMsg = messages.find((m) => m.status === 'generating' && !m.streaming)
    if (!genMsg || genMsg.serverIndex == null) return
    if (resumeAttemptedRef.current === `${currentId}:${genMsg.id}`) return
    resumeStream(currentId, genMsg.id, genMsg.serverIndex)
  }, [currentId, messages, resumeStream])

  // 兜底轮询: 重连不可用时（重连失败 / 进程重启导致无在途任务但消息仍 generating）,
  // 每 3 秒拉一次进度; 会话列表只在生成结束的那一轮刷新一次（侧栏生成中标记消失）
  const hasGeneratingMsg = messages.some((m) => m.status === 'generating')
  useEffect(() => {
    if (currentId == null || isStreaming || !hasGeneratingMsg) return
    let cancelled = false
    const timer = setInterval(() => {
      getConversationMessages(currentId)
        .then((msgs) => {
          if (cancelled) return
          useChatStore.getState().loadFromHistory(msgs)
          if (!msgs.some((m) => m.status === 'generating')) {
            loadConversations().catch(() => {})
          }
        })
        .catch(() => {
          /* 忽略单次轮询失败 */
        })
    }, 3000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [currentId, isStreaming, hasGeneratingMsg, loadConversations])

  // 切换会话时清除残留高亮: 消息下标在不同会话间没有对应关系,
  // 不清除会导致新会话中同下标的消息被误高亮
  useEffect(() => {
    setHighlightIndex(null)
  }, [currentId])

  // 搜索跳转定位: 消息渲染完成后滚动到目标消息并高亮 1 秒后消失。
  // 注意: 清除定时器存于 ref 而非 effect cleanup——本 effect 内部
  // setScrollTarget(null) 会触发自身重跑, cleanup 会把高亮定时器一并取消,
  // 导致高亮永不消失
  useEffect(() => {
    if (scrollTarget == null || messages.length === 0) return
    const el = scrollAreaRef.current?.querySelector<HTMLElement>(
      `[data-msg-index="${scrollTarget}"]`,
    )
    const target = scrollTarget
    setScrollTarget(null)
    if (!el) return
    setHighlightIndex(target)
    requestAnimationFrame(() => el.scrollIntoView({ behavior: 'smooth', block: 'center' }))
    if (highlightTimerRef.current != null) window.clearTimeout(highlightTimerRef.current)
    highlightTimerRef.current = window.setTimeout(() => {
      setHighlightIndex(null)
      highlightTimerRef.current = null
    }, 1000)
  }, [scrollTarget, messages, setScrollTarget])

  // 卸载时清理高亮定时器
  useEffect(() => () => {
    if (highlightTimerRef.current != null) window.clearTimeout(highlightTimerRef.current)
  }, [])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleCopy = useCallback(async (content: string): Promise<boolean> => {
    // copyText 内部含 execCommand 回退: navigator.clipboard 仅 HTTPS/localhost
    // 可用, 内网 HTTP 部署下直接调用会抛错
    const ok = await copyText(content)
    if (ok) toast.success('已复制到剪贴板')
    else toast.danger('复制失败')
    return ok
  }, [])

  const busy = isStreaming || hasGeneratingMsg

  return (
    <div className="flex size-full overflow-hidden">
      {/* 左侧栏: 通顶到底, 宽度+透明度过渡实现拉出/拉回动画 */}
      <div
        className={cn(
          'h-full shrink-0 overflow-hidden py-3 transition-all duration-300 ease-out',
          sidebarOpen ? 'ml-2 w-[240px] opacity-100' : 'ml-0 w-0 opacity-0',
        )}
      >
        <ConversationSidebar onOpenSettings={() => setSettingsOpen(true)} />
      </div>

      {/* 主对话区 */}
      <div className="flex min-w-0 grow flex-col gap-2 px-3 pb-3 pt-3">
        {/* 顶栏: 侧栏展开/收起开关 */}
        <div className="flex h-7 shrink-0 items-center">
          <Button
            variant="ghost"
            size="sm"
            isIconOnly
            className="size-7"
            onPress={() => setSidebarOpen((v) => !v)}
            aria-label={sidebarOpen ? '收起侧栏' : '展开侧栏'}
          >
            <PanelLeft className="size-4 text-muted" />
          </Button>
        </div>

        <div className="relative grow">
          {/* 消息滚动区。原实现用 HeroUI ScrollShadow, 它把 mask-image 渐隐遮罩
              直接盖在整个滚动容器上; 鼠标划过消息触发的 hover 重绘（操作行淡入、
              按钮 data-hovered 换色等）发生在遮罩内部, 会导致整个遮罩区域反复
              重新栅格化/合成, 在 Windows/Chromium 下表现为聊天内容（尤其顶部
              "思考耗时"徽标）随鼠标移动闪烁。现改为普通滚动容器 + 下方独立的
              渐变覆盖层实现同样的顶/底渐隐提示, 遮罩不再参与内容合成。 */}
          <div
            ref={scrollAreaRef}
            className="chat-msg-scroll absolute inset-0 flex flex-col overflow-y-auto p-4"
            onScroll={handleChatScroll}
          >
            {loadingMessages ? (
              // 切换会话的加载窗口: 显示加载态而非"开始对话"空状态, 避免空屏误导
              <div className="flex flex-1 items-center justify-center">
                <LoadingSpinner className="p-0" />
              </div>
            ) : messages.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted">
                <div className="flex size-14 items-center justify-center rounded-2xl bg-accent/10">
                  <MessagesSquare className="size-7 text-accent" />
                </div>
                <p className="text-sm">开始对话，向 AI 助手提问</p>
                <p className="text-xs text-muted/60">基于知识库检索增强 · 支持流式回答</p>
              </div>
            ) : (
              <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col gap-4">
                {messages.map((msg, i) => (
                  <div
                    key={msg.id}
                    data-msg-index={i}
                    className={cn(
                      'flex items-start gap-2 rounded-lg',
                      msg.role === 'user' ? 'justify-end' : 'justify-start',
                      highlightIndex === i && 'bg-accent/10 ring-1 ring-accent/30',
                    )}
                  >
                    {/* onCopy/onRegenerate 传稳定回调（不包内联闭包）,
                        让 ChatMessage 的 memo 真正生效: 输入框打字、
                        顶/底状态切换等 ChatPage 重渲染不再重渲染全部消息 */}
                    <ChatMessage
                      msg={msg}
                      onCopy={handleCopy}
                      onRegenerate={
                        msg.role === 'assistant' && !msg.streaming && msg.status !== 'generating'
                          ? handleRegenerate
                          : undefined
                      }
                      feedbackAction={msg.role === 'assistant' ? (feedbackByIndex[msg.serverIndex ?? -1] ?? null) : undefined}
                      onFeedback={
                        msg.role === 'assistant' && !msg.streaming && msg.status === 'done' && msg.serverIndex != null
                          ? (action) => handleFeedback(msg.serverIndex, action)
                          : undefined
                      }
                    />
                  </div>
                ))}
                <div ref={bottomRef} className="pb-1" />
              </div>
            )}
          </div>

          {/* 顶/底渐隐提示: 背景色渐变覆盖层（pointer-events-none 不影响交互）。
              页面底色为纯色 --background, 覆盖层视觉效果与 mask 渐隐等价,
              但独立于内容绘制, hover 重绘不会触发其重新合成。
              显隐不用 opacity 过渡: 滚动状态切换时的多帧渐变重绘是旧浏览器
              闪烁诱因, 直接切换即可（覆盖层本身只有 40px 高, 无过渡不突兀） */}
          <div
            aria-hidden
            className={cn(
              'pointer-events-none absolute inset-x-0 top-0 h-10 bg-[linear-gradient(180deg,var(--background),transparent)]',
              atTop || loadingMessages || messages.length === 0 ? 'opacity-0' : 'opacity-100',
            )}
          />
          <div
            aria-hidden
            className={cn(
              'pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-[linear-gradient(0deg,var(--background),transparent)]',
              atBottom || loadingMessages || messages.length === 0 ? 'opacity-0' : 'opacity-100',
            )}
          />

          {/* 回到底部: 仅在聊天区不在最底部时出现（显隐即时切换, 不用过渡） */}
          <Button
            variant="outline"
            size="sm"
            isIconOnly
            onPress={scrollToBottom}
            aria-label="回到底部"
            className={cn(
              'absolute bottom-2 left-1/2 z-10 size-9 -translate-x-1/2 rounded-full bg-surface shadow-md',
              atBottom || messages.length === 0
                ? 'pointer-events-none translate-y-2 opacity-0'
                : 'translate-y-0 opacity-100',
            )}
          >
            <ArrowDown className="size-4" />
          </Button>
        </div>

        {/* 输入区: 模型选择 + 流式开关 + 圆角输入框 + 发送（与消息列同宽居中） */}
        <div className="mx-auto w-full max-w-6xl shrink-0">
          <ChatComposer
            ref={inputRef}
            value={input}
            onChange={setInput}
            onSend={handleSend}
            onStop={handleStop}
            isStreaming={isStreaming}
            busy={busy}
            onKeyDown={handleKeyDown}
          />
        </div>
      </div>

      {/* 参数设置弹窗 */}
      <ChatSettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  )
}
