import { create } from 'zustand'
import { createSelectors } from '@/lib/createSelectors'
import type { Conversation } from '@/types/api'
import {
  listConversations,
  createConversation,
  deleteConversation,
  renameConversation,
  setConversationPin,
  getConversationMessages,
} from '@/api/conversations'
import { useChatStore } from '@/stores/chatStore'

interface ConversationState {
  conversations: Conversation[]
  currentId: number | null
  loading: boolean
  /** 正在加载某个会话的历史消息（切换会话的加载窗口, 聊天区据此显示加载态而非空状态） */
  loadingMessages: boolean

  loadConversations: () => Promise<void>
  startNew: () => void
  ensureCurrent: () => Promise<number>
  selectConversation: (id: number) => Promise<void>
  removeConversation: (id: number) => Promise<void>
  rename: (id: number, title: string) => Promise<void>
  setPinned: (id: number, pinned: boolean) => Promise<void>
}

const useConversationStoreBase = create<ConversationState>()((set, get) => ({
  conversations: [],
  currentId: null,
  loading: false,
  loadingMessages: false,

  loadConversations: async () => {
    set({ loading: true })
    try {
      const conversations = await listConversations()
      set({ conversations })
    } finally {
      set({ loading: false })
    }
  },

  // 新建对话：清空当前消息并将 currentId 置空（真正落库推迟到首次提问，避免产生空会话）
  startNew: () => {
    // 先中止本地 SSE 读取（服务端生成任务不受影响, 会继续生成并落盘）
    useChatStore.getState().stopStreaming()
    useChatStore.getState().clearMessages()
    set({ currentId: null, loadingMessages: false })
  },

  // 确保存在当前会话：无则创建并返回 id（首次提问时调用）
  ensureCurrent: async () => {
    const { currentId } = get()
    if (currentId != null) return currentId
    const conv = await createConversation()
    set((s) => ({ conversations: [conv, ...s.conversations], currentId: conv.id }))
    return conv.id
  },

  // 切换到指定会话：加载历史消息并重建聊天区。
  // 加载窗口内置 loadingMessages 标记: 聊天区显示加载态而非"开始对话"空状态,
  // 避免快速切换时出现误导性的空屏停留。
  selectConversation: async (id: number) => {
    if (get().currentId === id) return
    // 先中止上一条会话的本地 SSE 读取（服务端生成继续, 切回时可重连/轮询进度）
    useChatStore.getState().stopStreaming()
    set({ currentId: id, loadingMessages: true })
    useChatStore.getState().clearMessages()
    try {
      const messages = await getConversationMessages(id)
      // 响应可能在用户已切走后才到达: 仅当仍是目标会话时才渲染, 避免旧响应覆盖新会话
      if (get().currentId === id) {
        useChatStore.getState().loadFromHistory(messages)
      }
    } finally {
      if (get().currentId === id) set({ loadingMessages: false })
    }
  },

  removeConversation: async (id: number) => {
    await deleteConversation(id)
    set((s) => ({ conversations: s.conversations.filter((c) => c.id !== id) }))
    if (get().currentId === id) get().startNew()
  },

  rename: async (id: number, title: string) => {
    const updated = await renameConversation(id, title)
    set((s) => ({ conversations: s.conversations.map((c) => (c.id === id ? updated : c)) }))
  },

  // 置顶/取消置顶后重拉列表, 让后端按"置顶优先 + 最近活跃"重排
  setPinned: async (id: number, pinned: boolean) => {
    await setConversationPin(id, pinned)
    await get().loadConversations()
  },
}))

export const useConversationStore = createSelectors(useConversationStoreBase)
