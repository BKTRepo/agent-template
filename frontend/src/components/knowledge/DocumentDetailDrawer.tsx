import { useEffect, useState } from 'react'
import { Button, useOverlayState } from '@heroui/react'
import { toast } from '@/lib/toast'
import {
  Drawer,
  DrawerBackdrop,
  DrawerContent,
  DrawerDialog,
  DrawerHeader,
  DrawerHeading,
  DrawerBody,
  DrawerFooter,
  DrawerCloseTrigger,
} from '@heroui/react'
import { Check, Pencil, RotateCw } from 'lucide-react'
import { CopyButton } from '@/components/common/CopyButton'
import { OverlayPressTarget } from '@/components/common/OverlayPressTarget'
import { StatusLabel } from './StatusLabel'
import { useDocumentStore } from '@/stores/documentStore'
import { retryDocument } from '@/api/convert'
import { updateDocumentSummary } from '@/api/documents'
import type { Document } from '@/types/api'

interface Props {
  docId: string | null
  open: boolean
  onClose: () => void
}

/** 摘要最大字数 */
const SUMMARY_MAX_LEN = 15

/** 处理阶段定义: 配色与表格进度条一致 */
const STAGE_META: Record<string, { label: string; color: string }> = {
  parsing: { label: '内容解析', color: '#06b6d4' },
  terminology: { label: '术语提取', color: '#f97316' },
  analyzing: { label: '多模态分析', color: '#a855f7' },
  chunking: { label: '文档分块', color: '#6366f1' },
  embedding: { label: '向量嵌入', color: '#f59e0b' },
}

type StageState = 'done' | 'running' | 'failed'

interface StageInfo {
  key: string
  label: string
  color: string
  start: string
  end: string
  state: StageState
}

const COLOR_FAILED = '#ef4444'
const COLOR_FINISHED = '#10b981'

/** 组装已发生的阶段列表: 无开始时间的阶段（含被跳过的多模态分析）不展示。
 *  - 失败文档: 有开始时间但无结束时间的阶段即失败阶段, 标红作为终点;
 *  - 完成文档: 末尾追加绿色「已完成」终态节点（无起止时间与耗时）。 */
function buildStages(doc: Document): StageInfo[] {
  const candidates: (Omit<StageInfo, 'label' | 'color' | 'state'> | null)[] = [
    { key: 'parsing', start: doc.parse_start_time, end: doc.parse_end_time },
    { key: 'terminology', start: doc.term_start_time, end: doc.term_end_time },
    doc.analyzing_stage_skipped
      ? null
      : { key: 'analyzing', start: doc.analyze_start_time, end: doc.analyze_end_time },
    { key: 'chunking', start: doc.chunk_start_time, end: doc.chunk_end_time },
    { key: 'embedding', start: doc.embed_start_time, end: doc.embed_end_time },
  ]
  const stages: StageInfo[] = candidates
    .filter((s): s is Omit<StageInfo, 'label' | 'color' | 'state'> => !!s && !!s.start)
    .map((s) => ({
      ...s,
      ...STAGE_META[s.key]!,
      state: s.end ? 'done' : doc.status === 'failed' ? 'failed' : 'running',
    }))

  if (doc.status === 'complete') {
    stages.push({ key: 'finished', label: '已完成', color: COLOR_FINISHED, start: '', end: '', state: 'done' })
  } else if (doc.status === 'failed' && !stages.some((s) => s.state === 'failed')) {
    // 解析开始之前就失败的兜底: 补一个红色「失败」终态节点
    stages.push({ key: 'failed-node', label: '失败', color: COLOR_FAILED, start: '', end: '', state: 'failed' })
  }
  return stages
}

/** 将毫秒时长格式化为展示文案 */
function fmtMs(ms: number): string {
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)} 秒`
  const m = Math.floor(s / 60)
  const rs = Math.round(s - m * 60)
  if (m < 60) return `${m} 分 ${rs} 秒`
  return `${Math.floor(m / 60)} 时 ${m % 60} 分`
}

/** 由起止时间计算耗时展示文案 */
function fmtDuration(start: string, end: string): string | null {
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (!Number.isFinite(ms) || ms < 0) return null
  return fmtMs(ms)
}

function fmtTime(t: string): string {
  return t ? new Date(t).toLocaleString() : '-'
}

/** 基本信息行: 左侧浅灰标签 + 右侧值 */
function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <span className="shrink-0 text-xs text-muted">{label}</span>
      <span className="min-w-0 text-right text-sm text-foreground">{children}</span>
    </div>
  )
}

/**
 * 文档详情抽屉: 右侧滑出。上部分为基本信息, 分割线后为各处理阶段的时间线
 * （仅展示已发生的阶段, 含起止时间与耗时）。
 */
export function DocumentDetailDrawer({ docId, open, onClose }: Props) {
  const documents = useDocumentStore.use.documents()
  const updateDocument = useDocumentStore.use.updateDocument()
  const startPolling = useDocumentStore.use.startPolling()
  const found = docId ? documents.find((d) => d.id === docId) : null

  // 关闭时 docId 会立即置空, 但 Drawer 需要继续挂载以播放收回动画,
  // 因此缓存最后一次展示的文档, 退出动画期间用它继续渲染
  const [lastDoc, setLastDoc] = useState<Document | null>(null)
  useEffect(() => {
    if (found) setLastDoc(found)
  }, [found])
  const doc = found ?? lastDoc

  const state = useOverlayState({
    isOpen: open,
    onOpenChange: (isOpen) => {
      if (!isOpen) onClose()
    },
  })

  // 摘要行内编辑: 默认只读, 点铅笔进入编辑态（单行输入, ≤15 字）, 点对勾保存。
  // 仅状态为 complete 的文档允许编辑。切换文档时退出编辑态。
  const [editingSummary, setEditingSummary] = useState(false)
  const [summaryDraft, setSummaryDraft] = useState('')
  const [savingSummary, setSavingSummary] = useState(false)
  useEffect(() => {
    setEditingSummary(false)
    setSummaryDraft('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId])

  if (!doc) return null

  const startEditSummary = () => {
    setSummaryDraft((doc.summary ?? '').slice(0, SUMMARY_MAX_LEN))
    setEditingSummary(true)
  }

  const handleConfirmSummary = async () => {
    const next = summaryDraft.trim()
    if (next === (doc.summary ?? '')) {
      setEditingSummary(false)
      return
    }
    setSavingSummary(true)
    try {
      await updateDocumentSummary(doc.id, next)
      updateDocument(doc.id, { summary: next })
      toast.success('摘要已更新')
      setEditingSummary(false)
    } catch (err) {
      toast.danger(`保存失败: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setSavingSummary(false)
    }
  }

  const stages = buildStages(doc)
  // 总耗时 = 各阶段耗时之和。重试/续跑后各阶段计时可能来自不同轮次（已成功
  // 阶段保留上一轮计时）, 若用"最早开始 → 最终结束"相减会把轮次之间的空闲
  // 间隔也计入, 故按各阶段实际耗时求和（累计处理时长）
  let totalMs = 0
  let hasStageDuration = false
  for (const s of stages) {
    if (s.start && s.end) {
      const ms = new Date(s.end).getTime() - new Date(s.start).getTime()
      if (Number.isFinite(ms) && ms >= 0) {
        totalMs += ms
        hasStageDuration = true
      }
    }
  }
  const totalDuration = doc.process_end_time && hasStageDuration ? fmtMs(totalMs) : null

  const handleRetry = async () => {
    try {
      await retryDocument(doc.id)
      updateDocument(doc.id, {
        status: 'parsing', summary: '-', error_msg: '', error_trace: '',
        // 与后端重试逻辑一致: 不清空各阶段计时——已成功阶段保留上一轮计时,
        // 被重跑的阶段（失败阶段及其后续）随执行覆写为新计时
      })
      startPolling(doc.id)
      toast.success(`已提交重试: ${doc.filename}`)
      onClose()
    } catch (err) {
      toast.danger(`重试失败: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  return (
    <Drawer state={state}>
      {/* 受控抽屉无触发器子元素, 补一个隐藏 pressable 避免 react-aria dev 警告 */}
      <OverlayPressTarget />
      <DrawerBackdrop>
        <DrawerContent placement="right">
          <DrawerDialog className="sm:w-[28rem]">
            <DrawerHeader>
              <DrawerHeading className="text-base">文档详情</DrawerHeading>
              <DrawerCloseTrigger />
            </DrawerHeader>

            <DrawerBody>
              {/* ---- 基本信息 ---- */}
              <div className="divide-y divide-border/60 rounded-xl bg-default/40 px-4 py-1">
                <InfoRow label="文档 ID">
                  <span className="inline-flex max-w-full items-center gap-1.5">
                    <span className="truncate font-mono text-xs">{doc.id}</span>
                    <CopyButton text={doc.id} />
                  </span>
                </InfoRow>
                <InfoRow label="文件名">
                  <span className="inline-flex max-w-full items-center gap-1.5">
                    <span className="truncate font-medium">{doc.filename}</span>
                    <CopyButton text={doc.filename} />
                  </span>
                </InfoRow>
                <div className="flex items-center justify-between gap-3 py-2">
                  <span className="shrink-0 text-xs text-muted">摘要</span>
                  {editingSummary ? (
                    <div className="flex min-w-0 flex-1 items-center justify-end gap-1">
                      <input
                        value={summaryDraft}
                        onChange={(e) => setSummaryDraft(e.target.value.slice(0, SUMMARY_MAX_LEN))}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleConfirmSummary()
                          if (e.key === 'Escape') setEditingSummary(false)
                        }}
                        maxLength={SUMMARY_MAX_LEN}
                        autoFocus
                        placeholder="不超过15字"
                        className="h-7 min-w-0 flex-1 rounded-md border border-border bg-field px-2 text-sm text-foreground outline-none transition-colors placeholder:text-field-placeholder focus:border-accent"
                      />
                      <Button
                        variant="ghost"
                        size="sm"
                        isIconOnly
                        className="size-7 shrink-0"
                        aria-label="保存摘要"
                        isDisabled={savingSummary}
                        onPress={handleConfirmSummary}
                      >
                        <Check className="size-3.5 text-success" />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex min-w-0 items-center gap-1">
                      <span className="truncate text-sm text-foreground">{doc.summary || '-'}</span>
                      {doc.status === 'complete' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          isIconOnly
                          className="size-6 shrink-0"
                          aria-label="编辑摘要"
                          onPress={startEditSummary}
                        >
                          <Pencil className="size-3.5 text-muted" />
                        </Button>
                      )}
                    </div>
                  )}
                </div>
                <InfoRow label="状态">
                  <StatusLabel status={doc.status} />
                </InfoRow>
                <InfoRow label="OCR 引擎">RapidOCR</InfoRow>
                <InfoRow label="内容长度">
                  <span className="tabular-nums">{doc.content_length != null ? doc.content_length.toLocaleString() : '-'}</span>
                </InfoRow>
                <InfoRow label="分块策略">递归字符切分</InfoRow>
                <InfoRow label="分块数量">
                  <span className="tabular-nums">{doc.chunks_count ?? '-'}</span>
                </InfoRow>
              </div>

              {/* ---- 增量更新历史（仅更新过的文档展示, 最新在前） ---- */}
              {doc.update_history.length > 0 && (
                <>
                  <div className="my-5 flex items-center gap-3">
                    <div className="h-px flex-1 bg-border" />
                    <span className="text-xs font-medium text-muted">
                      增量更新历史（{doc.update_history.length} 次）
                    </span>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                  <div className="flex max-h-40 flex-col gap-2 overflow-auto">
                    {[...doc.update_history].reverse().map((h, i) => (
                      <div key={i} className="rounded-lg bg-default/40 px-3 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="whitespace-nowrap text-xs tabular-nums text-foreground">
                            {fmtTime(h.time)}
                          </span>
                          <span className="text-xs text-muted">
                            {h.reused != null && h.embedded != null
                              ? `复用 ${h.reused} / 新嵌入 ${h.embedded}`
                              : '复用统计不可知'}
                          </span>
                        </div>
                        <p className="mt-0.5 truncate text-xs text-muted">文件: {h.filename}</p>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {/* ---- 分割线 ---- */}
              <div className="my-5 flex items-center gap-3">
                <div className="h-px flex-1 bg-border" />
                <span className="text-xs font-medium text-muted">处理阶段</span>
                <div className="h-px flex-1 bg-border" />
              </div>

              {/* ---- 阶段时间线 ---- */}
              {stages.length === 0 ? (
                <p className="py-4 text-center text-xs text-muted">暂无阶段信息</p>
              ) : (
                <>
                  {totalDuration && (
                    <div className="mb-4 flex items-center justify-between rounded-lg bg-accent/10 px-3 py-2">
                      <span className="text-xs font-medium text-foreground">总耗时</span>
                      <span className="text-sm font-semibold tabular-nums text-accent">{totalDuration}</span>
                    </div>
                  )}
                  <ol>
                    {stages.map((stage, i) => {
                      const isFailed = stage.state === 'failed'
                      const dotColor = isFailed ? COLOR_FAILED : stage.color
                      // 终态节点（已完成/失败）与失败阶段不展示起止时间与耗时
                      const showTimes = stage.state === 'done' && !!stage.start && !!stage.end
                      const duration = showTimes ? fmtDuration(stage.start, stage.end) : null
                      const isLast = i === stages.length - 1
                      return (
                        <li key={stage.key} className="relative flex gap-3">
                          {/* 时间轴: 圆点 + 连接线 */}
                          <div className="flex flex-col items-center">
                            <span
                              className="mt-1.5 size-2.5 shrink-0 rounded-full ring-4 ring-transparent"
                              style={{ backgroundColor: dotColor, ['--tw-ring-color' as string]: `color-mix(in oklab, ${dotColor} 18%, transparent)` }}
                            />
                            {!isLast && <span className="w-px flex-1 bg-border" />}
                          </div>
                          {/* 阶段内容 */}
                          <div className={`min-w-0 flex-1 ${isLast ? 'pb-0' : 'pb-4'}`}>
                            <div className="flex items-center justify-between gap-2">
                              <span className={`text-sm font-medium ${isFailed ? 'text-danger' : 'text-foreground'}`}>
                                {stage.label}
                              </span>
                              {isFailed ? (
                                <span className="rounded-full bg-danger/15 px-2 py-0.5 text-xs font-medium text-danger">
                                  失败
                                </span>
                              ) : duration ? (
                                <span className="rounded-full bg-default px-2 py-0.5 text-xs font-medium tabular-nums text-muted">
                                  {duration}
                                </span>
                              ) : stage.state === 'running' ? (
                                <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs font-medium text-accent">
                                  进行中
                                </span>
                              ) : null}
                            </div>
                            {showTimes && (
                              <div className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs tabular-nums">
                                <span className="text-muted">开始</span>
                                <span className="text-foreground/80">{fmtTime(stage.start)}</span>
                                <span className="text-muted">结束</span>
                                <span className="text-foreground/80">{fmtTime(stage.end)}</span>
                              </div>
                            )}
                          </div>
                        </li>
                      )
                    })}
                  </ol>
                </>
              )}

              {/* ---- 失败信息 ---- */}
              {doc.status === 'failed' && (
                <div className="mt-5 rounded-xl border border-danger/30 bg-danger-soft p-3">
                  <p className="text-xs font-medium text-danger">错误信息</p>
                  <p className="mt-1 whitespace-pre-wrap break-all text-xs text-danger/90">{doc.error_msg || '-'}</p>
                  {doc.error_trace && (
                    <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-danger/10 p-2 font-mono text-[10px] text-danger/80">
                      {doc.error_trace}
                    </pre>
                  )}
                </div>
              )}
            </DrawerBody>

            {doc.status === 'failed' && (
              <DrawerFooter>
                <Button variant="primary" onPress={handleRetry}>
                  <RotateCw className="size-4" /> 重试
                </Button>
              </DrawerFooter>
            )}
          </DrawerDialog>
        </DrawerContent>
      </DrawerBackdrop>
    </Drawer>
  )
}
