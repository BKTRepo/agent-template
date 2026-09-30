import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { Button, useOverlayState } from '@heroui/react'
import {
  Drawer,
  DrawerBackdrop,
  DrawerContent,
  DrawerDialog,
  DrawerHeader,
  DrawerHeading,
  DrawerBody,
  DrawerCloseTrigger,
} from '@heroui/react'
import { FileWarning, Layers, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { OverlayPressTarget } from '@/components/common/OverlayPressTarget'
import { useDocumentStore } from '@/stores/documentStore'
import { getDocumentChunks } from '@/api/documents'
import type { DocChunk, Document } from '@/types/api'

interface Props {
  docId: string | null
  open: boolean
  onClose: () => void
}

/** 首屏立即渲染的卡片数（卡片较小, 可比 markdown 块多一些）。 */
const INITIAL_CARDS = 40
/** 每次滚动到底部附近时追加渲染的卡片数。 */
const LOAD_STEP = 40
/** 折叠态卡片正文截断长度（与展开阈值一致, 超长仅渲染前 N 字符缩小 DOM）。 */
const COLLAPSED_PREVIEW_CHARS = 400

/** 分块类型展示配置: 文本 / 图片描述 / 表格 / 表格行 */
const MODALITY_META: Record<string, { label: string; className: string }> = {
  text: {
    label: '文本',
    className: 'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800',
  },
  image: {
    label: '图片',
    className: 'bg-purple-100 text-purple-800 border-purple-300 dark:bg-purple-950 dark:text-purple-300 dark:border-purple-800',
  },
  table: {
    label: '表格',
    className: 'bg-orange-100 text-orange-800 border-orange-300 dark:bg-orange-950 dark:text-orange-300 dark:border-orange-800',
  },
  table_row: {
    label: '表格行',
    className: 'bg-teal-100 text-teal-800 border-teal-300 dark:bg-teal-950 dark:text-teal-300 dark:border-teal-800',
  },
}

/**
 * 单个分块卡片: 头部为序号 + 类型徽标 + token 数, 正文超长可展开。
 * memo 化: 渐进渲染追加新卡片时, 已渲染卡片不重渲。
 * 折叠态只渲染前 COLLAPSED_PREVIEW_CHARS 字符（而非全文 + CSS 裁剪）,
 * 大量卡片并存时显著缩小 DOM 文本体积。
 */
const ChunkCard = memo(function ChunkCard({ chunk }: { chunk: DocChunk }) {
  const [expanded, setExpanded] = useState(false)
  const meta = MODALITY_META[chunk.modality] ?? MODALITY_META.text!
  const isLong = chunk.content.length > COLLAPSED_PREVIEW_CHARS
  const displayContent =
    expanded || !isLong ? chunk.content : chunk.content.slice(0, COLLAPSED_PREVIEW_CHARS) + '…'

  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-background/40">
      <div className="flex items-center justify-between gap-2 border-b border-border/40 bg-default/30 px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="shrink-0 font-mono text-xs font-medium text-muted">#{chunk.order + 1}</span>
          <span className={cn('shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium', meta.className)}>
            {meta.label}
          </span>
        </div>
        <span className="shrink-0 tabular-nums text-xs text-muted">{chunk.tokens.toLocaleString()} tokens</span>
      </div>
      <div className="px-3 py-2">
        <pre
          className={cn(
            'whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground/90',
            !expanded && isLong && 'max-h-32 overflow-hidden',
          )}
        >
          {displayContent}
        </pre>
        {isLong && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-1.5 text-xs font-medium text-accent transition-opacity hover:opacity-80"
          >
            {expanded ? '收起 ▲' : '展开全部 ▼'}
          </button>
        )}
      </div>
    </div>
  )
})

/**
 * 分块结果抽屉: 展示文档最终存入向量库的分块列表。
 * 数据来自分块产物 chunks.json（流水线保证与向量库口径一致），
 * 支持按类型（文本/图片/表格/表格行）筛选。
 */
export function ChunksDrawer({ docId, open, onClose }: Props) {
  const documents = useDocumentStore.use.documents()
  const found = docId ? documents.find((d) => d.id === docId) : null

  // 关闭时 docId 立即置空, 缓存最后一次展示的文档以播放收回动画
  const [lastDoc, setLastDoc] = useState<Document | null>(null)
  useEffect(() => {
    if (found) setLastDoc(found)
  }, [found])
  const doc = found ?? lastDoc

  const [chunks, setChunks] = useState<DocChunk[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<string>('all')
  // 渐进渲染进度: 当前已渲染的卡片数（避免上万张卡片一次性挂载卡死主线程）
  const [visibleCount, setVisibleCount] = useState(0)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const load = (id: string) => {
    setLoading(true)
    setError('')
    getDocumentChunks(id)
      .then((res) => setChunks(res.chunks ?? []))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!open || !docId) return
    setChunks(null)
    setFilter('all')
    load(docId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, docId])

  // 各类型数量统计（仅统计实际存在的类型）
  const counts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const c of chunks ?? []) m[c.modality] = (m[c.modality] ?? 0) + 1
    return m
  }, [chunks])

  const visible = useMemo(() => {
    if (!chunks) return []
    return filter === 'all' ? chunks : chunks.filter((c) => c.modality === filter)
  }, [chunks, filter])

  // 可见列表变化（新加载 / 切换筛选）时重置渐进渲染进度
  useEffect(() => {
    setVisibleCount(visible.length ? Math.min(INITIAL_CARDS, visible.length) : 0)
  }, [visible])

  // 渐进渲染: 哨兵进入视口（含 800px 预加载余量）时追加渲染下一批卡片
  useEffect(() => {
    if (visibleCount >= visible.length) return
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisibleCount((c) => Math.min(visible.length, c + LOAD_STEP))
        }
      },
      { rootMargin: '800px 0px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [visibleCount, visible.length])

  const state = useOverlayState({
    isOpen: open,
    onOpenChange: (isOpen) => {
      if (!isOpen) onClose()
    },
  })

  if (!doc) return null

  return (
    <Drawer state={state}>
      {/* 受控抽屉无触发器子元素, 补一个隐藏 pressable 避免 react-aria dev 警告 */}
      <OverlayPressTarget />
      <DrawerBackdrop>
        <DrawerContent placement="right">
          <DrawerDialog className="sm:w-[46rem]">
            <DrawerHeader>
              <DrawerHeading className="flex items-center gap-2 text-base">
                <Layers className="size-4 text-muted" />
                分块结果
              </DrawerHeading>
              <DrawerCloseTrigger />
            </DrawerHeader>

            <DrawerBody>
              {/* 工具行: 文件名 + 分块总数 */}
              <div className="mb-3 flex items-center justify-between gap-2 rounded-lg bg-default/40 px-3 py-2">
                <span className="min-w-0 truncate font-mono text-xs text-muted">{doc.filename}</span>
                <span className="shrink-0 tabular-nums text-xs text-muted">
                  {chunks ? `共 ${chunks.length} 个分块` : '加载中'}
                </span>
              </div>

              {loading ? (
                <div className="flex flex-col items-center justify-center gap-2 py-20 text-muted">
                  <Loader2 className="size-6 animate-spin" />
                  <span className="text-xs">正在加载分块…</span>
                </div>
              ) : error ? (
                <div className="flex flex-col items-center justify-center gap-2 py-20">
                  <FileWarning className="size-6 text-danger" />
                  <span className="text-xs text-danger">加载失败: {error}</span>
                  <Button variant="outline" size="sm" className="mt-1" onPress={() => load(doc.id)}>
                    重新加载
                  </Button>
                </div>
              ) : !chunks?.length ? (
                <div className="py-20 text-center text-xs text-muted">
                  暂无分块数据（文档可能尚未完成分块入库）
                </div>
              ) : (
                <>
                  {/* 类型筛选 */}
                  <div className="mb-3 flex flex-wrap items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => setFilter('all')}
                      className={cn(
                        'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                        filter === 'all'
                          ? 'border-accent bg-accent text-accent-foreground'
                          : 'border-border bg-default/40 text-muted hover:bg-default',
                      )}
                    >
                      全部 {chunks.length}
                    </button>
                    {Object.entries(MODALITY_META)
                      .filter(([key]) => (counts[key] ?? 0) > 0)
                      .map(([key, meta]) => (
                        <button
                          key={key}
                          type="button"
                          onClick={() => setFilter(key)}
                          className={cn(
                            'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                            filter === key
                              ? 'border-accent bg-accent text-accent-foreground'
                              : 'border-border bg-default/40 text-muted hover:bg-default',
                          )}
                        >
                          {meta.label} {counts[key]}
                        </button>
                      ))}
                  </div>

                  {/* 分块列表（渐进渲染: 只挂载前 visibleCount 张, 滚动按需追加） */}
                  <div className="flex flex-col gap-2">
                    {visible.slice(0, visibleCount).map((chunk) => (
                      <ChunkCard key={chunk.id} chunk={chunk} />
                    ))}
                    {/* 无限滚动哨兵（不可见）: 滚动接近底部时静默追加渲染。
                        数据已在内存、追加为同步渲染, 无真实"加载中", 不展示常驻提示
                        ——顶部已显示"共 N 个分块", 用户可感知尚有更多分块。 */}
                    {visibleCount < visible.length && <div ref={sentinelRef} className="h-px" aria-hidden />}
                  </div>
                </>
              )}
            </DrawerBody>
          </DrawerDialog>
        </DrawerContent>
      </DrawerBackdrop>
    </Drawer>
  )
}
