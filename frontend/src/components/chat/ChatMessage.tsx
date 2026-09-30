import { memo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { ChevronDown, ChevronRight, Copy, Check, RefreshCw, Search, Zap, ThumbsUp, ThumbsDown } from 'lucide-react'
import { Button } from '@heroui/react'
import { cn, formatChatTime } from '@/lib/utils'
import type { ChatMessage as ChatMsg } from '@/stores/chatStore'
import type { Reference, RetrievalChunk } from '@/types/api'

// ---------------------------------------------------------------------------
// 子组件
// ---------------------------------------------------------------------------

function ReferencesSection({ refs }: { refs: Reference[] }) {
  if (!refs?.length) return null
  return (
    <div className="mt-3 border-t border-border pt-3 text-xs">
      <p className="mb-1 font-semibold">📚 References</p>
      <ol className="list-inside list-decimal space-y-0.5 text-muted">
        {refs.map((r, i) => (
          <li key={i}>{r.file_name || r.file_path || r.reference_id || `Reference ${i + 1}`}</li>
        ))}
      </ol>
    </div>
  )
}

function modalityBadge(modality: string) {
  const map: Record<string, string> = {
    table: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
    table_row: 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300',
    text: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  }
  return map[modality] || map.text
}

function RetrievalChunkRow({ chunk, rank }: { chunk: RetrievalChunk; rank: number }) {
  const [expanded, setExpanded] = useState(false)
  const isReranked = chunk.rerank_score != null
  const displayScore = isReranked ? (chunk.rerank_score as number) : chunk.score

  return (
    <div className="overflow-hidden rounded-md border border-border text-xs">
      {/* hover 换色即时生效（不带 transition-colors）: 过渡会把一次换色
          拉长成多帧连续重绘, 放大旧浏览器的合成闪烁 */}
      <button
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-default"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="min-w-[2rem] font-mono font-semibold text-muted">#{rank}</span>
        <span className="font-mono text-[11px] text-muted">{displayScore.toFixed(4)}</span>
        {isReranked && (
          <span className="rounded bg-purple-100 px-1 py-px text-[9px] font-medium text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">
            重排
          </span>
        )}
        <span className={cn('rounded px-1 py-px text-[10px] font-medium', modalityBadge(chunk.modality))}>
          {chunk.modality === 'table_row' ? '表格行' : chunk.modality === 'table' ? '表格' : '文本'}
        </span>
        <span className="text-[10px] uppercase text-muted/60">{chunk.source}</span>
        <span className="flex-1" />
        <span className="hidden max-w-[15rem] truncate text-[10px] text-muted/50 sm:inline">{chunk.file_name}</span>
        {expanded ? (
          <ChevronDown className="size-3 shrink-0 text-muted" />
        ) : (
          <ChevronRight className="size-3 shrink-0 text-muted" />
        )}
      </button>
      {expanded && (
        <div className="border-t border-border bg-default px-2.5 py-2">
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-muted">
            {chunk.full_content || chunk.content}
          </pre>
        </div>
      )}
    </div>
  )
}

function RetrievalDetailPanel({ detail }: { detail: NonNullable<ChatMsg['retrievalDetail']> }) {
  const [expanded, setExpanded] = useState(false)
  if (!detail?.chunks?.length) return null

  return (
    <div className="mt-1.5">
      <button
        className="flex items-center gap-1.5 text-xs text-muted/70 hover:text-muted"
        onClick={() => setExpanded(!expanded)}
      >
        <Search className="size-3" />
        <span>查看检索详情</span>
        {expanded ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
        <span className="text-muted/50">
          （{detail.final_count}/{detail.total_found} 条 · {detail.query_mode}）
        </span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-2 pl-1">
          {detail.rewritten_query && (
            <div className="text-xs italic text-muted/60">
              🔍 改写查询：<span className="not-italic">{detail.rewritten_query}</span>
            </div>
          )}
          <div className="max-h-[60vh] space-y-1 overflow-auto pr-1">
            {detail.chunks.map((chunk, i) => (
              <RetrievalChunkRow key={chunk.id || `${i}`} chunk={chunk} rank={i + 1} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

function ChatMessageComponent({ msg, onCopy, onRegenerate, feedbackAction, onFeedback }: {
  msg: ChatMsg
  onCopy?: (content: string) => Promise<boolean>
  onRegenerate?: (id: string) => void
  feedbackAction?: 'accepted' | 'revoked' | null
  onFeedback?: (action: 'accepted' | 'revoked') => Promise<void>
}) {
  const isUser = msg.role === 'user'
  const [thinkExpanded, setThinkExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  const isGenerating = msg.streaming || msg.status === 'generating'

  const handleCopy = async () => {
    // 仅在复制真正成功后才切换"已复制"图标（内网 HTTP 下 clipboard API
    // 不可用时由 onCopy 内部走 execCommand 回退）
    const ok = await onCopy?.(msg.content)
    if (ok === false) return
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const parseCOT = (content: string) => {
    const thinkMatch = content.match(/<think>([\s\S]*?)<\/think>/)
    if (!thinkMatch) return { thinking: null, display: content }
    return {
      thinking: thinkMatch[1].trim(),
      display: content.replace(/<think>[\s\S]*?<\/think>/, '').trim(),
    }
  }

  const { thinking, display } = isUser ? { thinking: null, display: msg.content } : parseCOT(msg.content)

  // ===== 用户消息（气泡样式, 与 AI 消息同色系） =====
  // 时间与复制按钮置于气泡外底部, 右对齐气泡右边界, 悬停时才显示
  if (isUser) {
    return (
      <div className="msg-in group flex max-w-[80%] flex-col items-end break-words">
        {/* 气泡用不透明底色: 半透明(bg-default/70)在 hover 重绘时需与下层
            重新混合, 旧浏览器/GPU 下是闪烁诱因之一 */}
        <div className="rounded-2xl bg-default px-4 py-2 text-sm text-foreground">
          <p className="whitespace-pre-wrap">{display}</p>
        </div>
        {/* 操作行: 悬停即时显示, 不用 opacity 过渡——过渡会让该行在
            hover 进出时反复经历合成层提升/降级, 旧版 Chromium 下表现为闪烁 */}
        <div className="mt-1 flex items-center gap-1 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100">
          <span className="text-xs text-muted">
            {formatChatTime(msg.timestamp)}
          </span>
          <Button variant="ghost" size="sm" isIconOnly className="size-6" onPress={handleCopy} aria-label="复制">
            {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          </Button>
        </div>
      </div>
    )
  }

  // ===== AI 消息（无气泡直出; 操作行悬停显示, 无分隔线） =====
  // w-full: 检索详情展开时与 AI 消息展示宽度一致
  return (
    <div className="msg-in group flex w-full min-w-0 flex-col gap-1 break-words text-sm">
      {/* 思考耗时（不透明底色, 理由同用户气泡） */}
      {!isGenerating && msg.thinkingMs != null && (
        <span className="w-fit inline-flex items-center gap-1 rounded-full bg-default px-2 py-0.5 text-[11px] tabular-nums text-muted">
          <Zap className="size-3 text-accent" />
          思考 {(msg.thinkingMs / 1000).toFixed(1)} 秒
        </span>
      )}

      {/* 检索详情（位于思考耗时下方, 展开宽度与消息区一致） */}
      {!isGenerating && msg.retrievalDetail && <RetrievalDetailPanel detail={msg.retrievalDetail} />}

      {/* AI 内容直出, 无气泡背景 */}
      <div>
        {/* 思考过程 */}
        {thinking && (
          <div className="mb-2">
            <button
              className="flex items-center gap-1 text-xs text-muted hover:text-foreground"
              onClick={() => setThinkExpanded(!thinkExpanded)}
            >
              {thinkExpanded ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              思考过程
            </button>
            {thinkExpanded && (
              <div className="mt-1 whitespace-pre-wrap border-l-2 border-accent/30 pl-4 text-xs text-muted">
                {thinking}
              </div>
            )}
          </div>
        )}

        {/* 思考中 */}
        {isGenerating && !display && (
          <div className="flex items-center gap-2.5 py-1.5">
            <span className="thinking-dots"><span /><span /><span /></span>
            <span className="animate-pulse text-sm text-muted">Thinking…</span>
          </div>
        )}

        {/* Markdown 正文（流式时末尾带闪烁光标） */}
        {display && (
          <div className="md-body text-appear text-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
              {display}
            </ReactMarkdown>
            {isGenerating && <span className="stream-cursor" aria-hidden />}
          </div>
        )}

        {/* 中断提示 */}
        {!isGenerating && msg.status === 'interrupted' && (
          <div className="py-1 text-xs text-warning">
            ⚠️ 回答未完成（生成已中断），{onRegenerate ? '可点击重新生成' : '已保留当前内容'}
          </div>
        )}

        {/* 参考文献 */}
        {!isGenerating && msg.references && <ReferencesSection refs={msg.references} />}
      </div>

      {/* 操作行: 时间(左对齐) + 复制 + 重新生成, 悬停即时显示（无过渡, 理由同用户消息操作行） */}
      {(!isGenerating || display) && (
        <div className="flex items-center gap-1 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100">
          <span className="text-xs text-muted">
            {formatChatTime(msg.timestamp)}
          </span>
          <Button variant="ghost" size="sm" isIconOnly className="size-6" onPress={handleCopy} aria-label="复制">
            {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          </Button>
          {!isGenerating && onRegenerate && (
            <Button variant="ghost" size="sm" isIconOnly className="size-6" onPress={() => onRegenerate(msg.id)} aria-label="重新生成">
              <RefreshCw className="size-3" />
            </Button>
          )}
          {!isGenerating && onFeedback && (
            <>
              <Button
                variant={feedbackAction === 'accepted' ? 'primary' : 'ghost'}
                size="sm"
                isIconOnly
                className="size-6"
                onPress={() => onFeedback(feedbackAction === 'accepted' ? 'revoked' : 'accepted')}
                aria-label={feedbackAction === 'accepted' ? '取消采纳' : '采纳回答'}
              >
                <ThumbsUp className="size-3" />
              </Button>
              {feedbackAction === 'accepted' && (
                <Button
                  variant="ghost"
                  size="sm"
                  isIconOnly
                  className="size-6"
                  onPress={() => onFeedback('revoked')}
                  aria-label="取消采纳"
                >
                  <ThumbsDown className="size-3" />
                </Button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export const ChatMessage = memo(ChatMessageComponent)
