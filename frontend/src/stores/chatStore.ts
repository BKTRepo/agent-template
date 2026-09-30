import { create } from 'zustand'
import { createSelectors } from '@/lib/createSelectors'
import type { MessageStatus, Reference, RetrievalDetail } from '@/types/api'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  references: Reference[] | null
  retrievalDetail: RetrievalDetail | null
  streaming: boolean
  timestamp: Date
  /**
   * 服务端消息状态。streaming 表示"本端正在接收流", status 表示"服务端持久化状态",
   * 二者解耦后刷新/切换会话也能据 status 还原"生成中 / 已中断"的展示。
   */
  status: MessageStatus
  /** 该消息在服务端会话中的下标（未持久化时为 null），重新生成/停止据此定位 */
  serverIndex: number | null
  /** 思考耗时（毫秒）: 流式=发起请求到首个正文片段, 非流式=整个请求耗时; 历史消息无 */
  thinkingMs: number | null
}

function genId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

/** 'yyyy-MM-dd HH:mm:ss' → Date; 空值/非法值回退当前时间（旧数据无时间字段时兜底） */
function parseMsgTime(s: string | undefined | null): Date {
  if (!s) return new Date()
  const d = new Date(s.replace(' ', 'T'))
  return Number.isNaN(d.getTime()) ? new Date() : d
}

interface ChatState {
  messages: ChatMessage[]
  conversationHistory: { role: string; content: string }[]
  isStreaming: boolean
  abortController: AbortController | null
  /** 搜索结果跳转定位: 目标消息在会话中的下标, 渲染后滚动到该消息并短暂高亮 */
  scrollTarget: number | null
  setScrollTarget: (index: number | null) => void

  addUserMessage: (content: string) => string
  addAssistantMessage: () => string
  appendContent: (chunk: string, msgId?: string) => void
  setReferences: (refs: Reference[], msgId?: string) => void
  setRetrievalDetail: (detail: RetrievalDetail, msgId?: string) => void
  finalizeStreaming: (msgId?: string) => void
  /** 重连前置位: 清空指定 assistant 消息的内容并置为收流中（replay 会从零重建全文） */
  resetForResume: (msgId: string) => void
  /** 标记某条 assistant 消息为中断（停止/出错），保留已生成内容 */
  markInterrupted: (msgId?: string) => void
  /** 把 persisted 事件返回的服务端下标写回对应的本地消息 */
  setServerIndices: (userIndex: number | null, assistantIndex: number | null) => void
  /** 记录某条 assistant 消息的思考耗时（默认最后一条） */
  setThinkingMs: (ms: number, msgId?: string) => void
  clearMessages: () => void
  setStreaming: (v: boolean) => void
  setAbortController: (ctrl: AbortController | null) => void
  stopStreaming: () => void
  replaceAssistantMessage: (oldMsgId: string) => string
  editUserMessage: (msgId: string, newContent: string) => void
  loadFromHistory: (history: {
    role: string
    content: string
    status?: MessageStatus
    created_time?: string
    thinking_ms?: number | null
    retrieval?: import('@/types/api').RetrievalDetail | null
  }[]) => void
}

const useChatStoreBase = create<ChatState>()((set, get) => ({
  messages: [],
  conversationHistory: [],
  isStreaming: false,
  abortController: null,
  scrollTarget: null,
  setScrollTarget: (scrollTarget) => set({ scrollTarget }),

  addUserMessage: (content) => {
    const id = genId()
    const msg: ChatMessage = {
      id,
      role: 'user',
      content,
      references: null,
      retrievalDetail: null,
      streaming: false,
      timestamp: new Date(),
      status: 'done',
      serverIndex: null,
      thinkingMs: null,
    }
    set((s) => ({
      messages: [...s.messages, msg],
      conversationHistory: [
        ...s.conversationHistory,
        { role: 'user', content },
      ],
    }))
    return id
  },

  addAssistantMessage: () => {
    const id = genId()
    const msg: ChatMessage = {
      id,
      role: 'assistant',
      content: '',
      references: null,
      retrievalDetail: null,
      streaming: true,
      timestamp: new Date(),
      // 服务端占位消息此时即为 generating, 本地与服务端状态保持一致
      status: 'generating',
      serverIndex: null,
      thinkingMs: null,
    }
    set((s) => ({ messages: [...s.messages, msg] }))
    return id
  },

  appendContent: (chunk: string, msgId?: string) =>
    set((s) => {
      const msgs = [...s.messages]
      const idx = msgId ? msgs.findIndex((m) => m.id === msgId) : msgs.length - 1
      if (idx === -1) return {}
      const target = msgs[idx]
      if (target && target.role === 'assistant') {
        msgs[idx] = { ...target, content: target.content + chunk }
      }
      return { messages: msgs }
    }),

  setReferences: (refs, msgId?) =>
    set((s) => {
      const msgs = [...s.messages]
      const idx = msgId ? msgs.findIndex((m) => m.id === msgId) : msgs.length - 1
      if (idx === -1) return {}
      const target = msgs[idx]
      if (target && target.role === 'assistant') {
        msgs[idx] = { ...target, references: refs }
      }
      return { messages: msgs }
    }),

  setRetrievalDetail: (detail, msgId?) =>
    set((s) => {
      const msgs = [...s.messages]
      const idx = msgId ? msgs.findIndex((m) => m.id === msgId) : msgs.length - 1
      if (idx === -1) return {}
      const target = msgs[idx]
      if (target && target.role === 'assistant') {
        msgs[idx] = { ...target, retrievalDetail: detail }
      }
      return { messages: msgs }
    }),

  resetForResume: (msgId) =>
    set((s) => {
      const idx = s.messages.findIndex((m) => m.id === msgId)
      if (idx === -1) return {}
      const target = s.messages[idx]
      if (!target || target.role !== 'assistant') return {}
      const msgs = [...s.messages]
      // 持久化快照里的部分内容一并清空: 重连 replay 携带本轮全部内容, 重建即完整
      msgs[idx] = {
        ...target,
        content: '',
        references: null,
        retrievalDetail: null,
        streaming: true,
        status: 'generating',
      }
      return { messages: msgs }
    }),

  finalizeStreaming: (msgId?: string) =>
    set((s) => {
      const msgs = [...s.messages]
      const idx = msgId ? msgs.findIndex((m) => m.id === msgId) : msgs.length - 1
      if (idx === -1) return {}
      const target = msgs[idx]
      if (target && target.role === 'assistant') {
        msgs[idx] = { ...target, streaming: false, status: 'done' }
        const newHistory = [...s.conversationHistory]
        if (idx < newHistory.length) {
          newHistory[idx] = { role: 'assistant', content: target.content }
        } else {
          newHistory.push({ role: 'assistant', content: target.content })
        }
        return { messages: msgs, conversationHistory: newHistory }
      }
      return {}
    }),

  markInterrupted: (msgId?: string) =>
    set((s) => {
      const msgs = [...s.messages]
      const idx = msgId ? msgs.findIndex((m) => m.id === msgId) : msgs.length - 1
      if (idx === -1) return {}
      const target = msgs[idx]
      // 仅对"收流中/服务端生成中"的消息生效, 避免误伤已完成的消息
      if (target && target.role === 'assistant' && (target.streaming || target.status === 'generating')) {
        // 中断只改状态, 已生成内容原样保留（与服务端 interrupted 语义一致）
        msgs[idx] = { ...target, streaming: false, status: 'interrupted' }
        return { messages: msgs }
      }
      return {}
    }),

  setServerIndices: (userIndex, assistantIndex) =>
    set((s) => {
      const msgs = [...s.messages]
      let changed = false
      // 从尾部向前定位最近一条 user / assistant 消息写下标（本轮刚追加的即为目标）
      if (userIndex != null) {
        for (let i = msgs.length - 1; i >= 0; i--) {
          const m = msgs[i]
          if (m && m.role === 'user' && m.serverIndex == null) {
            msgs[i] = { ...m, serverIndex: userIndex }
            changed = true
            break
          }
        }
      }
      if (assistantIndex != null) {
        for (let i = msgs.length - 1; i >= 0; i--) {
          const m = msgs[i]
          if (m && m.role === 'assistant' && m.serverIndex == null) {
            msgs[i] = { ...m, serverIndex: assistantIndex }
            changed = true
            break
          }
        }
      }
      return changed ? { messages: msgs } : {}
    }),

  // Atomically replace an assistant message in-place (for regeneration).
  // Returns the new message ID so callers can stream content into it.
  replaceAssistantMessage: (oldMsgId: string) => {
    const newId = genId()
    set((s) => {
      const idx = s.messages.findIndex((m) => m.id === oldMsgId)
      if (idx === -1) return {}
      const old = s.messages[idx]
      const newMsg: ChatMessage = {
        id: newId,
        role: 'assistant',
        content: '',
        references: null,
        retrievalDetail: null,
        streaming: true,
        timestamp: new Date(),
        status: 'generating',
        // 重新生成复用同一服务端消息槽位, 继承下标
        serverIndex: old ? old.serverIndex : null,
        thinkingMs: null,
      }
      const msgs = [...s.messages]
      msgs[idx] = newMsg
      return { messages: msgs }
    })
    return newId
  },

  // Edit a user message in-place — only updates content, keeps everything else
  editUserMessage: (msgId: string, newContent: string) =>
    set((s) => {
      const idx = s.messages.findIndex((m) => m.id === msgId)
      if (idx === -1) return {}
      const msgs = [...s.messages]
      msgs[idx] = { ...msgs[idx], content: newContent }
      // Also update the matching conversationHistory entry
      const newHistory = s.conversationHistory.map((h, i) =>
        i === idx ? { ...h, content: newContent } : h
      )
      return { messages: msgs, conversationHistory: newHistory }
    }),

  // 从会话历史加载消息（切换/恢复会话时重建 messages 与 conversationHistory）
  // 数组下标即服务端消息下标（serverIndex）, status 还原"生成中/已中断"展示;
  // thinking_ms / retrieval 为持久化的思考耗时与检索详情（旧消息可能缺失）。
  // id 采用"角色-下标"的确定性生成方式, 且内容无变化的消息复用原对象引用——
  // 生成中轮询每轮回调本方法时, React key 保持稳定、未变消息不重渲染,
  // 避免整列表卸载重挂导致的入场动画重播与界面抽搐。
  loadFromHistory: (history) => {
    set((s) => {
      const prev = s.messages
      const msgs: ChatMessage[] = history.map((h, i) => {
        const role = (h.role === 'assistant' ? 'assistant' : 'user') as 'user' | 'assistant'
        const status = h.status ?? 'done'
        const thinkingMs = h.thinking_ms ?? null
        const retrievalDetail = h.retrieval ?? null
        const stableId = `${role}-${i}`
        const p = prev[i]
        if (
          p && p.id === stableId && p.content === h.content && p.status === status
          && p.thinkingMs === thinkingMs && p.retrievalDetail === retrievalDetail
        ) {
          return p
        }
        return {
          id: stableId,
          role,
          content: h.content,
          references: null,
          retrievalDetail,
          streaming: false,
          timestamp: parseMsgTime(h.created_time),
          status,
          serverIndex: i,
          thinkingMs,
        }
      })
      return {
        messages: msgs,
        conversationHistory: history.map((h) => ({ role: h.role, content: h.content })),
        isStreaming: false,
      }
    })
  },

  setThinkingMs: (ms, msgId?) =>
    set((s) => {
      const msgs = [...s.messages]
      const idx = msgId ? msgs.findIndex((m) => m.id === msgId) : msgs.length - 1
      if (idx === -1) return {}
      const target = msgs[idx]
      if (target && target.role === 'assistant') {
        msgs[idx] = { ...target, thinkingMs: ms }
        return { messages: msgs }
      }
      return {}
    }),

  clearMessages: () =>
    set({ messages: [], conversationHistory: [], isStreaming: false }),

  setStreaming: (v) => set({ isStreaming: v }),
  setAbortController: (ctrl) => set({ abortController: ctrl }),

  stopStreaming: () => {
    const { abortController } = get()
    abortController?.abort()
    // 停止 = 中断（服务端同样置 interrupted 并保留已生成内容）
    get().markInterrupted()
    set({ abortController: null, isStreaming: false })
  },
}))

export const useChatStore = createSelectors(useChatStoreBase)
