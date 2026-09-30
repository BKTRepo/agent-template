import { useState, useEffect, useRef } from 'react'
import { Activity, ArrowDown } from 'lucide-react'
import { Button } from '@heroui/react'
import { toast } from '@/lib/toast'
import { AppModal } from '@/components/common/Modal'
import { cancelPipeline, getPipelineStatus } from '@/api/pipeline'
import type { PipelineStatus } from '@/types/api'

interface Props {
  open: boolean
  onClose: () => void
}

export function PipelineDialog({ open, onClose }: Props) {
  const [showCancel, setShowCancel] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [status, setStatus] = useState<PipelineStatus | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const consoleRef = useRef<HTMLDivElement | null>(null)
  const [atBottom, setAtBottom] = useState(true)

  // 打开时拉取并轮询流水线状态
  useEffect(() => {
    if (!open) {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      return
    }
    const fetch = async () => {
      try {
        const s = await getPipelineStatus()
        setStatus(s)
      } catch {
        /* retry next tick */
      }
    }
    fetch()
    pollRef.current = setInterval(fetch, 2000)
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [open])

  useEffect(() => {
    if (open) setAtBottom(true)
  }, [open])

  const msgCount = status?.history_messages?.length ?? 0
  useEffect(() => {
    const el = consoleRef.current
    if (!el || !open || !atBottom) return
    el.scrollTop = el.scrollHeight
  }, [msgCount, open, atBottom])

  const handleConsoleScroll = () => {
    const el = consoleRef.current
    if (!el) return
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 24)
  }

  const handleCancel = async () => {
    setCancelling(true)
    try {
      const res = await cancelPipeline()
      toast.info(res.message || '已请求取消')
      setShowCancel(false)
    } catch {
      toast.danger('取消失败')
    } finally {
      setCancelling(false)
    }
  }

  const busy = status?.busy ?? false
  const cancelled = status?.cancellation_requested ?? false

  return (
    <>
      <AppModal
        open={open}
        onClose={onClose}
        size="lg"
        title={
          <span className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            流水线状态
          </span>
        }
        dialogClassName="max-w-3xl"
      >
        <div className="flex flex-col gap-3 text-sm">
          {/* 状态行 */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5">
                <span className="font-medium">运行中:</span>
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: busy ? '#22c55e' : '#999' }}
                />
              </div>
              <div className="flex items-center gap-1.5">
                <span className="font-medium">等待中:</span>
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: status?.request_pending ? '#22c55e' : '#999' }}
                />
              </div>
              {cancelled && <span className="font-medium text-danger">已请求取消</span>}
            </div>
            {busy && !cancelled && (
              <Button variant="danger" size="sm" onPress={() => setShowCancel(true)}>终止流水线</Button>
            )}
          </div>

          {/* 任务信息 */}
          <div className="space-y-1 rounded-lg border border-border p-3">
            <div>
              任务名称: <span className="font-medium">{status?.job_name || '-'}</span>
            </div>
            <div className="flex justify-between">
              <span>
                开始时间: <span className="font-medium">{status?.job_start || '-'}</span>
              </span>
              <span>
                进度:{' '}
                <span className="font-medium">
                  {status ? `${status.cur_batch}/${status.batchs || status.docs || 0} 个任务` : '-'}
                  {status && status.part_total > 0 ? ` (子文档 ${status.part_done}/${status.part_total})` : ''}
                </span>
              </span>
            </div>
          </div>

          {/* 控制台 */}
          <div className="relative">
            <p className="mb-1 font-medium">流水线消息:</p>
            <div
              ref={consoleRef}
              onScroll={handleConsoleScroll}
              className="max-h-60 overflow-auto rounded-lg bg-zinc-900 p-3 font-mono text-xs leading-relaxed text-green-400"
            >
              {status?.history_messages?.length
                ? status.history_messages.map((m, i) => <div key={i}>{m}</div>)
                : '暂无消息'}
            </div>
            {!atBottom && (
              <button
                onClick={() => {
                  const el = consoleRef.current
                  if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
                  setAtBottom(true)
                }}
                className="absolute bottom-2 right-2 flex items-center gap-1 rounded-full bg-zinc-700/90 px-2.5 py-1 text-xs text-zinc-100 shadow transition-colors hover:bg-zinc-600"
              >
                <ArrowDown className="h-3 w-3" />
                最新消息
              </button>
            )}
          </div>
        </div>
      </AppModal>

      {/* 取消确认子弹窗 */}
      <AppModal
        open={showCancel}
        onClose={() => setShowCancel(false)}
        size="xs"
        title={<span className="text-danger">确认终止流水线？</span>}
        description="此操作将取消所有正在进行的转换任务，已完成的文档不受影响。"
        footer={
          <>
            <Button variant="outline" onPress={() => setShowCancel(false)}>取消</Button>
            <Button variant="danger" onPress={handleCancel} isDisabled={cancelling}>
              {cancelling ? '处理中...' : '确认终止'}
            </Button>
          </>
        }
      >
        <span className="sr-only">确认终止流水线</span>
      </AppModal>
    </>
  )
}
