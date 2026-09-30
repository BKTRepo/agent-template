import { useEffect, useState, useCallback } from 'react'
import { Card, CardHeader, CardTitle, CardContent, Button } from '@heroui/react'
import { RefreshCw, Activity, Trash2, Upload, CheckSquare, X } from 'lucide-react'
import { DocumentTable } from '@/components/knowledge/DocumentTable'
import { DocumentSearch } from '@/components/knowledge/DocumentSearch'
import { UploadDialog } from '@/components/knowledge/UploadDialog'
import { UpdateDialog } from '@/components/knowledge/UpdateDialog'
import { DocumentDetailDrawer } from '@/components/knowledge/DocumentDetailDrawer'
import { MarkdownDrawer } from '@/components/knowledge/MarkdownDrawer'
import { TerminologyDrawer } from '@/components/knowledge/TerminologyDrawer'
import { ChunksDrawer } from '@/components/knowledge/ChunksDrawer'
import { PipelineDialog } from '@/components/knowledge/PipelineDialog'
import { ClearDialog } from '@/components/knowledge/ClearDialog'
import { AppModal } from '@/components/common/Modal'
import { toast } from '@/lib/toast'
import { rollbackDocument } from '@/api/convert'
import { useDocumentStore } from '@/stores/documentStore'
import { usePipelineStore } from '@/stores/pipelineStore'
import { cn } from '@/lib/utils'

export default function KnowledgePage() {
  const fetchDocuments = useDocumentStore.use.fetchDocuments()
  const stopAllPolling = useDocumentStore.use.stopAllPolling()
  const documents = useDocumentStore.use.documents()
  const selectedIds = useDocumentStore.use.selectedIds()
  const hasSelection = useDocumentStore.use.hasSelection()
  const selectAll = useDocumentStore.use.selectAll()
  const deselectAll = useDocumentStore.use.deselectAll()
  const updateDocument = useDocumentStore.use.updateDocument()
  const startPolling = useDocumentStore.use.startPolling()
  const hasActiveJobs = useDocumentStore.use.hasActiveJobs()
  const pipelineBusy = usePipelineStore.use.status()?.busy ?? false

  const [uploadOpen, setUploadOpen] = useState(false)
  const [pipelineOpen, setPipelineOpen] = useState(false)
  const [clearOpen, setClearOpen] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [markdownId, setMarkdownId] = useState<string | null>(null)
  const [terminologyId, setTerminologyId] = useState<string | null>(null)
  const [chunksId, setChunksId] = useState<string | null>(null)
  const [updateId, setUpdateId] = useState<string | null>(null)
  const [rollbackId, setRollbackId] = useState<string | null>(null)

  useEffect(() => {
    fetchDocuments()
    return () => stopAllPolling()
  }, [])

  const handleOpenDetail = useCallback((docId: string) => setDetailId(docId), [])
  const handleOpenMarkdown = useCallback((docId: string) => setMarkdownId(docId), [])
  const handleOpenTerminology = useCallback((docId: string) => setTerminologyId(docId), [])
  const handleOpenChunks = useCallback((docId: string) => setChunksId(docId), [])
  const handleOpenUpdate = useCallback((docId: string) => setUpdateId(docId), [])
  const handleOpenRollback = useCallback((docId: string) => setRollbackId(docId), [])

  // 回滚确认: 更新失败的文档问答仍在用旧版本数据, 回滚是可选的恢复动作——
  // 恢复上一版本的产物目录/文档字段并重写向量, 状态经 embedding 回到 complete
  const rollbackDoc = rollbackId ? documents.find((d) => d.id === rollbackId) ?? null : null
  const confirmRollback = useCallback(async () => {
    if (!rollbackId) return
    const id = rollbackId
    setRollbackId(null)
    try {
      await rollbackDocument(id)
      updateDocument(id, {
        status: 'embedding',
        summary: '正在回滚到上一版本',
        error_msg: '',
        error_trace: '',
        is_updating: false,
      })
      startPolling(id)
      toast.success('已提交回滚')
    } catch (err) {
      toast.danger(`回滚失败: ${err instanceof Error ? err.message : String(err)}`)
    }
  }, [rollbackId, updateDocument, startPolling])

  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden !rounded-none !shadow-none">
      <CardHeader className="px-6 py-3">
        <CardTitle className="text-lg">文档管理</CardTitle>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col overflow-auto px-6 pb-4">
        {/* 工具栏 */}
        <div className="mb-3 mt-3 flex flex-wrap items-center justify-between gap-x-2 gap-y-2">
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onPress={fetchDocuments}>
              <RefreshCw className="size-4" /> 刷新
            </Button>
            <Button
              variant="outline"
              size="sm"
              onPress={() => setPipelineOpen(true)}
              className={cn(pipelineBusy && 'pipeline-busy')}
            >
              <Activity className="size-4" /> 流水线
            </Button>
            <DocumentSearch onOpenDetail={handleOpenDetail} />
          </div>
          <div className="flex gap-2">
            {hasSelection() ? (
              <>
                {selectedIds.size < documents.length ? (
                  <Button variant="outline" size="sm" onPress={selectAll}>
                    <CheckSquare className="size-4" /> 全选
                  </Button>
                ) : (
                  <Button variant="outline" size="sm" onPress={deselectAll}>
                    <X className="size-4" /> 取消全选
                  </Button>
                )}
                <Button variant="outline" size="sm" onPress={() => setClearOpen(true)}>
                  <Trash2 className="size-4" /> 删除 ({selectedIds.size})
                </Button>
              </>
            ) : (
              <Button variant="outline" size="sm" onPress={() => setClearOpen(true)} isDisabled={documents.length === 0}>
                <Trash2 className="size-4" /> 清除
              </Button>
            )}
            <span
              className="inline-flex"
              onClick={() => {
                if (hasActiveJobs()) toast.info('有文档正在上传，暂不能上传其他文档')
              }}
            >
              <Button
                variant="primary"
                size="sm"
                onPress={() => setUploadOpen(true)}
                isDisabled={hasActiveJobs()}
                className={cn(hasActiveJobs() && 'pointer-events-none')}
              >
                <Upload className="size-4" /> 上传
              </Button>
            </span>
          </div>
        </div>

        {/* 表格 */}
        <DocumentTable
          onOpenDetail={handleOpenDetail}
          onOpenMarkdown={handleOpenMarkdown}
          onOpenTerminology={handleOpenTerminology}
          onOpenChunks={handleOpenChunks}
          onOpenUpdate={handleOpenUpdate}
          onOpenRollback={handleOpenRollback}
        />
      </CardContent>

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} onOpenUpdate={handleOpenUpdate} />
      <DocumentDetailDrawer docId={detailId} open={detailId !== null} onClose={() => setDetailId(null)} />
      <MarkdownDrawer docId={markdownId} open={markdownId !== null} onClose={() => setMarkdownId(null)} />
      <TerminologyDrawer docId={terminologyId} open={terminologyId !== null} onClose={() => setTerminologyId(null)} />
      <ChunksDrawer docId={chunksId} open={chunksId !== null} onClose={() => setChunksId(null)} />
      <PipelineDialog open={pipelineOpen} onClose={() => setPipelineOpen(false)} />
      <ClearDialog open={clearOpen} onClose={() => setClearOpen(false)} />
      <UpdateDialog docId={updateId} open={updateId !== null} onClose={() => setUpdateId(null)} />

      {/* 回滚确认弹窗 */}
      <AppModal
        open={rollbackId !== null}
        onClose={() => setRollbackId(null)}
        title="回滚到上一版本"
        description={rollbackDoc ? `文档 "${rollbackDoc.filename}" 增量更新失败` : undefined}
        size="sm"
        footer={
          <>
            <Button variant="outline" onPress={() => setRollbackId(null)}>取消</Button>
            <Button variant="danger" onPress={confirmRollback}>确认回滚</Button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-foreground/80">
          问答目前仍在使用旧版本数据, 回滚非必需。确认后文档将恢复到本次更新前的状态
          （解析产物、向量与记录信息）, 状态回到「已完成」。
        </p>
      </AppModal>
    </Card>
  )
}
