import { useCallback, useEffect, useRef, useState } from 'react'
import { FileUp, X, FileText } from 'lucide-react'
import { Button } from '@heroui/react'
import { toast } from '@/lib/toast'
import { AppModal } from '@/components/common/Modal'
import { updateDocumentFile } from '@/api/convert'
import { useDocumentStore } from '@/stores/documentStore'
import { fmtSize } from '@/lib/utils'
import type { Document } from '@/types/api'

interface Props {
  docId: string | null
  open: boolean
  onClose: () => void
}

/** 上传大小上限（字节）: 与后端 RAG_MAX_UPLOAD_MB=200 保持一致 */
const MAX_SIZE_BYTES = 200 * 1024 * 1024

/**
 * 增量更新弹窗: 以新文件替换既有文档（保留同一 job_id, 重跑流水线）。
 *
 * - 文件名不可改: 后端沿用原文档名, 更新成功后新文件才顶替旧文件;
 * - 解析配置（OCR / VLM）沿用首次上传, 此处不可修改;
 * - 更新期间问答继续使用旧版本向量, 新版本处理成功后才切换;
 * - 文件内容哈希与现有版本一致时后端直接跳过（unchanged）。
 */
export function UpdateDialog({ docId, open, onClose }: Props) {
  const documents = useDocumentStore.use.documents()
  const updateDocument = useDocumentStore.use.updateDocument()
  const startPolling = useDocumentStore.use.startPolling()

  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 关闭时 docId 立即置空, 退出动画期间用缓存文档继续渲染
  const found = docId ? documents.find((d) => d.id === docId) : null
  const [lastDoc, setLastDoc] = useState<Document | null>(null)
  useEffect(() => {
    if (found) setLastDoc(found)
  }, [found])
  const doc = found ?? lastDoc

  // 每次打开重置暂存文件与提交状态
  useEffect(() => {
    if (open) {
      setFile(null)
      setSubmitting(false)
    }
  }, [open])

  const pickFile = useCallback((f: File | null | undefined) => {
    if (!f) return
    if (f.type !== 'application/pdf' && !f.name.toLowerCase().endsWith('.pdf')) {
      toast.danger(`${f.name} 不是 PDF 文件`)
      return
    }
    if (f.size > MAX_SIZE_BYTES) {
      toast.danger(`${f.name} 超过 200MB 限制`)
      return
    }
    setFile(f)
  }, [])

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    pickFile(e.dataTransfer.files?.[0])
  }

  const handleSubmit = async () => {
    if (!doc || !file) return
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await updateDocumentFile(doc.id, fd)
      if (res.unchanged) {
        // 文件内容哈希一致: 后端未触发重处理, 无需轮询
        toast.info('文件内容与现有版本一致, 已跳过更新', { timeout: 3000 })
      } else {
        // 与后端 submit_update 的状态重置对齐: 乐观更新本地状态并启动轮询
        updateDocument(doc.id, {
          status: res.parts > 1 ? 'splitting' : 'parsing',
          summary: '-',
          error_msg: '',
          error_trace: '',
          total_parts: res.parts,
          completed_parts: 0,
          content_length: null,
          chunks_count: null,
          is_updating: true,
        })
        startPolling(doc.id)
        toast.success(`已提交增量更新: ${res.filename}`)
      }
      onClose()
    } catch (err) {
      toast.danger(`更新提交失败: ${err instanceof Error ? err.message : String(err)}`)
      setSubmitting(false)
    }
  }

  return (
    <AppModal
      open={open}
      onClose={onClose}
      title="增量更新文档"
      description="以新版本文件替换现有文档, 处理期间问答仍使用旧版本"
      size="lg"
      footer={
        <>
          <Button variant="outline" onPress={onClose}>取消</Button>
          <Button variant="primary" onPress={handleSubmit} isDisabled={!file || submitting}>
            {submitting ? (
              '提交中...'
            ) : (
              <>
                <FileUp className="size-4" /> 开始更新
              </>
            )}
          </Button>
        </>
      }
    >
      {doc && (
        <div className="flex flex-col gap-4">
          {/* 文件名固定 + 现有版本信息 */}
          <div className="rounded-lg bg-default/60 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <FileText className="size-4 shrink-0 text-muted" />
              <span className="truncate text-sm font-medium text-foreground">{doc.filename}</span>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-center">
              <div className="rounded-md border border-border bg-background px-1 py-1.5">
                <p className="text-[11px] text-muted">内容长度</p>
                <p className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">
                  {doc.content_length != null ? doc.content_length.toLocaleString() : '-'}
                </p>
              </div>
              <div className="rounded-md border border-border bg-background px-1 py-1.5">
                <p className="text-[11px] text-muted">分块数量</p>
                <p className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">
                  {doc.chunks_count ?? '-'}
                </p>
              </div>
              <div className="rounded-md border border-border bg-background px-1 py-1.5">
                <p className="text-[11px] text-muted">已更新次数</p>
                <p className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">
                  {doc.update_history.length}
                </p>
              </div>
            </div>
            <p className="mt-2 text-xs text-muted">
              更新后保留原文件名, 解析配置（OCR / VLM）沿用首次上传; 新版本处理成功后才顶替旧版本, 失败可回滚。
            </p>
          </div>

          {/* 新文件选择区 */}
          <div
            className="grid h-32 w-full cursor-pointer place-items-center rounded-xl border-2 border-dashed border-muted px-5 text-center transition hover:bg-default/50"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
          >
            <div className="flex flex-col items-center gap-1.5">
              <div className="rounded-full border border-dashed border-muted p-2.5">
                <FileUp className="size-5 text-muted" />
              </div>
              <p className="text-sm font-medium text-muted">拖拽新版本 PDF 到此处，或点击选择文件</p>
              <p className="text-xs text-muted/70">支持 .pdf 格式，最大 200 MB</p>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              className="hidden"
              onChange={(e) => {
                pickFile(e.target.files?.[0])
                e.target.value = ''
              }}
            />
          </div>

          {/* 已选文件 */}
          {file && (
            <div className="flex items-center gap-2.5 rounded-lg bg-default/60 px-3 py-2">
              <FileText className="size-5 shrink-0 text-muted" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-foreground">{file.name}</p>
                <p className="text-xs text-muted">{fmtSize(file.size)}</p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                isIconOnly
                className="size-7 shrink-0"
                aria-label="移除所选文件"
                onPress={() => setFile(null)}
              >
                <X className="size-4" />
              </Button>
            </div>
          )}
        </div>
      )}
    </AppModal>
  )
}
