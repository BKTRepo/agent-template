import { useState, useRef, useCallback, useEffect } from 'react'
import { Upload, X, FileText } from 'lucide-react'
import { Button, Input } from '@heroui/react'
import { toast } from '@/lib/toast'
import { AppModal } from '@/components/common/Modal'
import { SwitchField } from '@/components/common/SwitchField'
import { convertPdf } from '@/api/convert'
import { useDocumentStore } from '@/stores/documentStore'
import { fmtSize } from '@/lib/utils'

interface Props {
  open: boolean
  onClose: () => void
  /** 重名冲突时跳转既有文档的增量更新（由知识页打开 UpdateDialog） */
  onOpenUpdate?: (docId: string) => void
}

interface StagedFile {
  file: File
  size: string
}

export function UploadDialog({ open, onClose, onOpenUpdate }: Props) {
  const [files, setFiles] = useState<StagedFile[]>([])
  const [forceOcr, setForceOcr] = useState(false)
  const [enableVlm, setEnableVlm] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const documents = useDocumentStore.use.documents()
  const fetchDocuments = useDocumentStore.use.fetchDocuments()
  const addDocument = useDocumentStore.use.addDocument()
  const startPolling = useDocumentStore.use.startPolling()
  const uploading = useDocumentStore.use.uploading()
  const setUploading = useDocumentStore.use.setUploading()

  // 重名文件重命名队列（逐个弹窗处理）
  const [renameQueue, setRenameQueue] = useState<File[]>([])
  const [renameValue, setRenameValue] = useState('')
  const [renameError, setRenameError] = useState('')

  const suggestName = useCallback(
    (name: string) => {
      const stem = name.replace(/\.pdf$/i, '')
      const taken = new Set([
        ...documents.map((d) => d.filename.toLowerCase()),
        ...files.map((sf) => sf.file.name.toLowerCase()),
      ])
      let i = 1
      let candidate = `${stem}_${i}.pdf`
      while (taken.has(candidate.toLowerCase())) {
        i += 1
        candidate = `${stem}_${i}.pdf`
      }
      return candidate
    },
    [documents, files],
  )

  useEffect(() => {
    if (renameQueue.length > 0) {
      setRenameValue(suggestName(renameQueue[0].name))
      setRenameError('')
    }
  }, [renameQueue, suggestName])

  const confirmRename = () => {
    const target = renameQueue[0]
    if (!target) return
    const value = renameValue.trim()
    if (!value) {
      setRenameError('文件名不能为空')
      return
    }
    const finalName = /\.pdf$/i.test(value) ? value : `${value}.pdf`
    const taken = new Set([
      ...documents.map((d) => d.filename.toLowerCase()),
      ...files.map((sf) => sf.file.name.toLowerCase()),
    ])
    if (taken.has(finalName.toLowerCase())) {
      setRenameError(`文件名 "${finalName}" 仍然重复, 请换一个`)
      return
    }
    const renamed = new File([target], finalName, { type: target.type || 'application/pdf' })
    setFiles((prev) => [...prev, { file: renamed, size: fmtSize(renamed.size) }])
    setRenameQueue((prev) => prev.slice(1))
  }

  const skipRename = () => setRenameQueue((prev) => prev.slice(1))

  // 重名冲突对应的既有文档（大小写不敏感）: 存在则引导走增量更新而非重命名重传。
  // 仅 complete 文档允许更新（与后端 /convert/update 状态门一致）; 失败文档
  // 需先重试/回滚, 不作跳转引导。
  const conflictTargetDoc = renameQueue[0]
    ? documents.find(
        (d) =>
          d.filename.toLowerCase() === renameQueue[0].name.toLowerCase() &&
          d.status === 'complete',
      ) ?? null
    : null

  const goUpdateInstead = () => {
    if (!conflictTargetDoc) return
    setRenameQueue([])
    onClose()
    onOpenUpdate?.(conflictTargetDoc.id)
  }

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const newFiles: StagedFile[] = []
      const conflicts: File[] = []
      const taken = new Set([
        ...documents.map((d) => d.filename.toLowerCase()),
        ...files.map((sf) => sf.file.name.toLowerCase()),
      ])
      for (const f of incoming) {
        if (f.type !== 'application/pdf' && !f.name.toLowerCase().endsWith('.pdf')) {
          toast.danger(`${f.name} 不是 PDF 文件`)
          continue
        }
        if (f.size > 200 * 1024 * 1024) {
          toast.danger(`${f.name} 超过 200MB 限制`)
          continue
        }
        if (files.some((sf) => sf.file.name === f.name && sf.file.size === f.size)) continue
        if (taken.has(f.name.toLowerCase())) {
          conflicts.push(f)
          continue
        }
        taken.add(f.name.toLowerCase())
        newFiles.push({ file: f, size: fmtSize(f.size) })
      }
      setFiles((prev) => [...prev, ...newFiles])
      if (conflicts.length > 0) setRenameQueue((prev) => [...prev, ...conflicts])
    },
    [files, documents],
  )

  const removeFile = (i: number) => setFiles((prev) => prev.filter((_, idx) => idx !== i))

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    if (e.dataTransfer.files) addFiles(e.dataTransfer.files)
  }

  const uploadOne = useCallback(
    async (sf: StagedFile): Promise<boolean> => {
      const fd = new FormData()
      fd.append('file', sf.file)
      fd.append('force_ocr', String(forceOcr))
      fd.append('enable_vlm', String(enableVlm))
      try {
        const res = await convertPdf(fd)
        addDocument({
          id: res.job_id, filename: res.filename,
          status: res.parts > 1 ? 'splitting' : 'parsing', summary: '-',
          content_length: null, chunks_count: null, total_parts: res.parts,
          completed_parts: 0, terminology_total_batches: 1, terminology_completed_batches: 0,
          chunks_file: '', input_path: '',
          created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
          parse_start_time: new Date().toISOString(), parse_end_time: '',
          parse_duration: null, term_start_time: '', term_end_time: '',
          analyze_start_time: '', analyze_end_time: '',
          analyzing_stage_skipped: false, chunk_start_time: '', chunk_end_time: '',
          embed_start_time: '', embed_end_time: '', process_end_time: '',
          error_msg: '', error_trace: '',
          // 新上传文档的增量更新字段初始值（后端首次提交不写 file_sha256 以外字段）
          file_sha256: '', is_updating: false, update_history: [], rollback_available: false,
        })
        startPolling(res.job_id)
        return true
      } catch (err) {
        toast.danger(`${sf.file.name} 提交失败: ${err instanceof Error ? err.message : String(err)}`)
        return false
      }
    },
    [forceOcr, enableVlm, addDocument, startPolling],
  )

  const handleStart = async () => {
    if (files.length === 0 || uploading) return
    setUploading(true)
    const queue = [...files]
    let okCount = 0
    let failCount = 0
    const worker = async () => {
      while (queue.length > 0) {
        const sf = queue.shift()!
        if (await uploadOne(sf)) okCount += 1
        else failCount += 1
      }
    }
    await Promise.all(Array.from({ length: Math.min(3, queue.length) }, () => worker()))
    if (failCount === 0) toast.success(`已全部提交 ${okCount} 个文件`)
    else toast.warning(`上传结束: 成功 ${okCount} 个, 失败 ${failCount} 个`)
    setFiles([])
    setUploading(false)
    onClose()
  }

  const handleOpenChange = (o: boolean) => {
    if (o) {
      fetchDocuments()
    } else {
      setFiles([])
      setRenameQueue([])
      onClose()
    }
  }

  return (
    <>
      <AppModal
        open={open}
        onClose={() => handleOpenChange(false)}
        title="上传 PDF 文件"
        description="上传 PDF 文件并通过 Docling 转换为 Markdown 格式"
        size="lg"
        isDismissable={!uploading}
        hideClose={uploading}
        footer={
          <>
            <Button variant="outline" onPress={() => handleOpenChange(false)} isDisabled={uploading}>取消</Button>
            <Button variant="primary" onPress={handleStart} isDisabled={files.length === 0 || uploading}>
              {uploading ? (
                '提交中...'
              ) : (
                <>
                  <Upload className="size-4" /> 上传
                </>
              )}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          {/* 拖拽区 */}
          <div
            className="grid h-44 w-full cursor-pointer place-items-center rounded-xl border-2 border-dashed border-muted px-5 py-2.5 text-center transition hover:bg-default/50"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
          >
            <div className="flex flex-col items-center gap-2">
              <div className="rounded-full border border-dashed border-muted p-3">
                <Upload className="size-6 text-muted" />
              </div>
              <p className="text-sm font-medium text-muted">拖拽 PDF 文件到此处，或点击选择文件</p>
              <p className="text-xs text-muted/70">支持 .pdf 格式，最大 200 MB</p>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              multiple
              className="hidden"
              onChange={(e) => e.target.files && addFiles(e.target.files)}
            />
          </div>

          {/* 文件列表 */}
          {files.length > 0 && (
            <div className="flex max-h-36 flex-col gap-2 overflow-auto">
              {files.map((sf, i) => (
                <div key={i} className="flex items-center gap-2.5 rounded-lg bg-default/60 px-3 py-2">
                  <FileText className="size-5 shrink-0 text-muted" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-foreground">{sf.file.name}</p>
                    <p className="text-xs text-muted">{sf.size}</p>
                  </div>
                  <Button variant="ghost" size="sm" isIconOnly className="size-7 shrink-0" onPress={() => removeFile(i)}>
                    <X className="size-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          {/* 选项 */}
          <div className="flex flex-row flex-wrap items-center gap-x-6 gap-y-3 border-t border-border pt-4 text-sm">
            <SwitchField isSelected={forceOcr} onChange={setForceOcr}>强制 OCR</SwitchField>
            <SwitchField isSelected={enableVlm} onChange={setEnableVlm}>启用 VLM 多模态分析</SwitchField>
          </div>
        </div>
      </AppModal>

      {/* 重名文件重命名弹窗 */}
      <AppModal
        open={renameQueue.length > 0}
        onClose={skipRename}
        title="文件名已存在"
        description={`文件 "${renameQueue[0]?.name}" 与已有文档重名，请修改文件名后上传`}
        size="sm"
        footer={
          <>
            <Button variant="outline" onPress={skipRename}>跳过该文件</Button>
            {conflictTargetDoc && (
              <Button variant="outline" onPress={goUpdateInstead}>去更新该文档</Button>
            )}
            <Button variant="primary" onPress={confirmRename}>确定</Button>
          </>
        }
      >
        <div className="flex flex-col gap-2">
          {conflictTargetDoc && (
            <p className="rounded-lg bg-accent/10 px-3 py-2 text-xs leading-relaxed text-foreground/80">
              若此文件是「{conflictTargetDoc.filename}」的新版本, 建议直接增量更新该文档:
              沿用原文件名与解析配置, 问答自动切换到新版本, 无需重命名重新上传。
            </p>
          )}
          <Input
            value={renameValue}
            autoFocus
            onChange={(e) => {
              setRenameValue(e.target.value)
              setRenameError('')
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') confirmRename()
            }}
          />
          {renameError && <p className="text-xs text-danger">{renameError}</p>}
        </div>
      </AppModal>
    </>
  )
}
