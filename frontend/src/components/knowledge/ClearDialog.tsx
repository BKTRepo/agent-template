import { useState } from 'react'
import { Button } from '@heroui/react'
import { toast } from '@/lib/toast'
import { AlertTriangle } from 'lucide-react'
import { AppModal } from '@/components/common/Modal'
import { useDocumentStore } from '@/stores/documentStore'
import { deleteFiles } from '@/api/files'
import { cancelPipeline } from '@/api/pipeline'

interface Props {
  open: boolean
  onClose: () => void
}

/** 清除/删除确认弹窗: 二次确认即可, 默认连同解析产物目录一起删除 */
export function ClearDialog({ open, onClose }: Props) {
  const [deleting, setDeleting] = useState(false)

  const selectedIds = useDocumentStore.use.selectedIds()
  const hasSelection = useDocumentStore.use.hasSelection()
  const documents = useDocumentStore.use.documents()
  const removeDocuments = useDocumentStore.use.removeDocuments()
  const stopAllPolling = useDocumentStore.use.stopAllPolling()
  const deselectAll = useDocumentStore.use.deselectAll()

  const targetIds = hasSelection() ? [...selectedIds] : documents.map((d) => d.id)
  const targetDocs = documents.filter((d) => targetIds.includes(d.id))
  const isAll = !hasSelection()

  const handleConfirm = async () => {
    setDeleting(true)
    try {
      const hasRunning = targetDocs.some((d) =>
        ['parsing', 'terminology', 'analyzing', 'chunking', 'embedding'].includes(d.status),
      )
      if (hasRunning) {
        try {
          await cancelPipeline()
        } catch {
          // best effort
        }
        stopAllPolling()
      }

      // 源文件留档、解析产物目录与向量分块均由服务端按 job_id 推导清理
      await deleteFiles(targetIds)
      removeDocuments(targetIds)
      deselectAll()
      toast.success(`已删除 ${targetIds.length} 个文档`)
      onClose()
    } catch (err) {
      toast.danger(`删除失败: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <AppModal
      open={open}
      onClose={onClose}
      size="sm"
      isDismissable={!deleting}
      hideClose={deleting}
      title={
        <span className="flex items-center gap-2 text-danger">
          <AlertTriangle className="h-5 w-5" />
          {isAll ? '确认清除全部文档' : `确认删除所选文档 (${targetIds.length})`}
        </span>
      }
      description={
        isAll
          ? '将删除全部文档、解析产物目录及其关联数据，此操作不可恢复'
          : `将删除 ${targetIds.length} 个选中文档、解析产物目录及其关联数据，此操作不可恢复`
      }
      footer={
        <>
          <Button variant="outline" onPress={onClose} isDisabled={deleting}>取消</Button>
          <Button variant="danger" onPress={handleConfirm} isDisabled={deleting}>
            {deleting ? '删除中...' : isAll ? '确认清除' : '确认删除'}
          </Button>
        </>
      }
    >
      <></>
    </AppModal>
  )
}
