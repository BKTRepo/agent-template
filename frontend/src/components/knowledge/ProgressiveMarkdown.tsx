import { memo, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { splitMarkdownIntoChunks } from '@/lib/markdownChunks'

/** 首次立即渲染的块数（保证首屏秒开, 后续滚动渐进加载）。 */
const INITIAL_CHUNKS = 3
/** 每次滚动到底部附近时追加渲染的块数。 */
const LOAD_STEP = 2
/** 超过该字符数禁用语法高亮（高亮为渲染重开销, 超大规范文档多为表格, 收益低）。 */
const HIGHLIGHT_MAX_CHARS = 1_000_000

/**
 * 单个 markdown 块的渲染器（memo 缓存）: visibleCount 变化时已渲染的块不重渲,
 * 只有新追加的块参与渲染, 主线程每次只处理一小块 → 大文档不卡顿。
 */
const MarkdownChunk = memo(function MarkdownChunk({
  text,
  highlight,
}: {
  text: string
  highlight: boolean
}) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={highlight ? [rehypeHighlight] : []}>
      {text}
    </ReactMarkdown>
  )
})

/**
 * 大 markdown 渐进渲染器（MarkdownDrawer / TerminologyDrawer 共用）:
 * 全文按标题/空行安全切块（splitMarkdownIntoChunks）, 首屏只渲染前几块,
 * 其余块由 IntersectionObserver 在滚动接近底部时渐进渲染——避免一次性渲染整份
 * 大文档（十万级 DOM 节点同步挂载导致主线程长时间阻塞）。
 */
export function ProgressiveMarkdown({ markdown }: { markdown: string }) {
  // 已渲染的块数（渐进渲染进度）
  const [visibleCount, setVisibleCount] = useState(0)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  // 切块（markdown 变化时重新切分）
  const chunks = useMemo(() => splitMarkdownIntoChunks(markdown), [markdown])
  const enableHighlight = markdown.length < HIGHLIGHT_MAX_CHARS

  // 新 markdown 加载完成后, 重置为先渲染前几块
  useEffect(() => {
    setVisibleCount(chunks.length ? Math.min(INITIAL_CHUNKS, chunks.length) : 0)
  }, [chunks])

  // 渐进渲染: 哨兵进入视口（含 600px 预加载余量）时追加渲染下一批块
  useEffect(() => {
    if (visibleCount >= chunks.length) return
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisibleCount((c) => Math.min(chunks.length, c + LOAD_STEP))
        }
      },
      { rootMargin: '600px 0px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [visibleCount, chunks.length])

  const hasMore = visibleCount < chunks.length

  return (
    <div className="md-body rounded-xl border border-border/60 bg-background/40 p-4 text-sm">
      {chunks.slice(0, visibleCount).map((chunk, i) => (
        <MarkdownChunk key={i} text={chunk} highlight={enableHighlight} />
      ))}
      {/* 无限滚动哨兵（不可见）: 滚动接近底部时静默追加渲染。
          数据已在内存、追加为同步渲染, 无真实"加载中", 不展示常驻提示
          ——顶部已显示总字符数, 用户可感知尚有更多内容。 */}
      {hasMore && <div ref={sentinelRef} className="h-px" aria-hidden />}
    </div>
  )
}
