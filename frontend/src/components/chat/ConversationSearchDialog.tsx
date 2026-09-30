import { useEffect, useRef, useState } from 'react'
import { Search, SearchX } from 'lucide-react'
import {
  Modal, ModalBackdrop, ModalContainer, ModalDialog, Skeleton,
} from '@heroui/react'
import { OverlayPressTarget } from '@/components/common/OverlayPressTarget'
import { searchConversations } from '@/api/conversations'
import { useConversationStore } from '@/stores/conversationStore'
import { useChatStore } from '@/stores/chatStore'
import type { ConversationSearchMatch } from '@/types/api'

/** 会话时间展示: 当年显示「8月5日 22:53」, 跨年显示「2025年10月1日 22:53」 */
function formatTime(s: string): string {
  if (!s) return ''
  const d = new Date(s.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return s
  const now = new Date()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (d.getFullYear() === now.getFullYear()) {
    return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
  }
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
}

/** 将文本中所有关键词出现位置用主题色高亮（忽略大小写匹配, 原样保留原文） */
function Highlighted({ text, query }: { text: string; query: string }) {
  const q = query.trim().toLowerCase()
  if (!q) return <>{text}</>
  const lower = text.toLowerCase()
  const parts: React.ReactNode[] = []
  let from = 0
  let idx = lower.indexOf(q)
  let key = 0
  while (idx !== -1) {
    if (idx > from) parts.push(text.slice(from, idx))
    parts.push(
      <mark key={key++} className="rounded-sm bg-accent/15 px-px font-medium text-accent">
        {text.slice(idx, idx + q.length)}
      </mark>,
    )
    from = idx + q.length
    idx = lower.indexOf(q, from)
  }
  if (from < text.length) parts.push(text.slice(from))
  return <>{parts}</>
}

/** 搜索加载中的骨架屏 */
function SearchSkeleton() {
  return (
    <div className="flex flex-col gap-1 p-1">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="flex items-start gap-3 px-2.5 py-2">
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-4 w-1/3 rounded-md" />
            <Skeleton className="h-3 w-full rounded-md" />
            <Skeleton className="h-3 w-4/5 rounded-md" />
          </div>
          <Skeleton className="mt-0.5 h-3 w-20 shrink-0 rounded-md" />
        </div>
      ))}
    </div>
  )
}

interface Props {
  open: boolean
  onClose: () => void
}

/**
 * 会话搜索弹窗（Ctrl+K / 侧栏搜索按钮唤起）。
 * 结构: 单个弹窗容器, 内部顶部为独立的搜索输入框（自带边框背景, 不与弹窗
 * 边框融为一体）, 下方为结果区。
 * - 未输入关键词: 展示「最近对话」, 按最近提问时间从先到后排列;
 * - 输入关键词: 防抖搜索用户提问与 AI 回答, 命中项展示会话名 + 角色标记
 *   （提问/回答）+ 高亮内容片段 + 该消息自身的时间; 点击跳转并定位到对应消息。
 */
export function ConversationSearchDialog({ open, onClose }: Props) {
  const conversations = useConversationStore.use.conversations()
  const selectConversation = useConversationStore.use.selectConversation()
  const setScrollTarget = useChatStore.use.setScrollTarget()

  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<ConversationSearchMatch[]>([])
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const requestSeq = useRef(0)

  // 打开时重置状态并聚焦输入框
  useEffect(() => {
    if (!open) return
    setQuery('')
    setMatches([])
    setSearched(false)
    setSearching(false)
    const t = setTimeout(() => inputRef.current?.focus(), 50)
    return () => clearTimeout(t)
  }, [open])

  // 关键词防抖搜索（300ms）; 序号防止旧响应覆盖新结果
  const q = query.trim()
  useEffect(() => {
    if (!open) return
    if (!q) {
      setMatches([])
      setSearched(false)
      setSearching(false)
      return
    }
    setSearching(true)
    const seq = ++requestSeq.current
    const timer = setTimeout(() => {
      searchConversations(q)
        .then((res) => {
          if (seq !== requestSeq.current) return
          setMatches(res)
          setSearched(true)
          setSearching(false)
        })
        .catch(() => {
          if (seq !== requestSeq.current) return
          setMatches([])
          setSearched(true)
          setSearching(false)
        })
    }, 300)
    return () => clearTimeout(timer)
  }, [q, open])

  /** 跳转到指定会话; messageIndex 非空时渲染后滚动定位到该消息 */
  const goTo = async (conversationId: number, messageIndex: number | null) => {
    onClose()
    await selectConversation(conversationId)
    if (messageIndex != null) setScrollTarget(messageIndex)
  }

  // 最近对话: 按最近提问时间从先到后（升序）
  const recent = [...conversations].sort((a, b) =>
    (a.last_question_time || a.updated_time || '')
      .localeCompare(b.last_question_time || b.updated_time || ''),
  )

  return (
    <Modal
      isOpen={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) onClose()
      }}
    >
      {/* 受控弹层无触发器子元素, 补一个隐藏 pressable 避免 react-aria dev 警告 */}
      <OverlayPressTarget />
      <ModalBackdrop isDismissable>
        <ModalContainer size="lg">
          {/* 单个弹窗容器: 顶部是独立的搜索输入框, 下方为结果区 */}
          <ModalDialog className="max-w-3xl p-0">
            {/* 独立搜索输入框: 自带边框与背景, 聚焦时边框变主题色 */}
            <div className="px-4 pt-4">
              <div className="flex items-center gap-2 rounded-xl border border-border bg-default/40 px-3 py-2.5 transition-colors focus-within:border-accent/60">
                <Search className="size-4 shrink-0 text-muted" />
                <input
                  ref={inputRef}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') onClose()
                  }}
                  placeholder="搜索"
                  aria-label="搜索对话内容"
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted/60"
                />
                {query && (
                  <button
                    type="button"
                    onClick={() => {
                      setQuery('')
                      inputRef.current?.focus()
                    }}
                    className="shrink-0 text-xs text-accent transition-opacity hover:opacity-75"
                  >
                    清除
                  </button>
                )}
              </div>
            </div>

            {/* 结果区: 搜索结果 / 最近对话 */}
            <div className="mt-3 max-h-[62vh] min-h-[280px] overflow-y-auto px-2 pb-3">
              {q ? (
                searching ? (
                  <SearchSkeleton />
                ) : searched && matches.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 py-16 text-muted">
                    <SearchX className="size-6" />
                    <p className="text-sm">未找到相关对话</p>
                    <p className="text-xs text-muted/60">换个关键词试试</p>
                  </div>
                ) : (
                  <div className="flex flex-col gap-0.5">
                    {matches.map((m) => (
                      <button
                        key={`${m.conversation_id}-${m.message_index}`}
                        type="button"
                        onClick={() => goTo(m.conversation_id, m.message_index)}
                        className="flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-default/60"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium">
                            {m.conversation_title}
                          </div>
                          <div className="mt-0.5 line-clamp-3 text-xs leading-relaxed text-muted">
                            <span className="mr-1.5 inline-block rounded bg-default px-1 py-px align-middle text-[10px] font-medium text-foreground/70">
                              {m.role === 'user' ? '提问' : '回答'}
                            </span>
                            <Highlighted text={m.content} query={q} />
                          </div>
                        </div>
                        <span className="shrink-0 pt-0.5 text-xs tabular-nums text-muted">
                          {formatTime(m.created_time)}
                        </span>
                      </button>
                    ))}
                  </div>
                )
              ) : (
                <>
                  <div className="px-2.5 pb-1 pt-1.5 text-xs font-medium text-muted">
                    最近对话
                  </div>
                  <div className="flex flex-col gap-0.5">
                    {recent.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => goTo(c.id, null)}
                        className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-default/60"
                      >
                        <span className="min-w-0 flex-1 truncate text-sm">{c.title}</span>
                        <span className="shrink-0 text-xs tabular-nums text-muted">
                          {formatTime(c.last_question_time || c.updated_time || '')}
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          </ModalDialog>
        </ModalContainer>
      </ModalBackdrop>
    </Modal>
  )
}
