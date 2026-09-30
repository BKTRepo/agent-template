import { useState } from 'react'
import { Button } from '@heroui/react'
import { toast } from '@/lib/toast'
import { AlertTriangle } from 'lucide-react'
import { AppModal } from '@/components/common/Modal'
import { useDocumentStore } from '@/stores/documentStore'
import { deleteFiles } from '@/api/files'

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
  const fetchDocuments = useDocumentStore.use.fetchDocuments()
  const deselectAll = useDocumentStore.use.deselectAll()

  const targetIds = hasSelection() ? [...selectedIds] : documents.map((d) => d.id)
  const isAll = !hasSelection()

  const handleConfirm = async () => {
    setDeleting(true)
    try {
      // 服务端只取消所选文档，并异步清理产物；不能停止其他文档的流水线。
      const result = await deleteFiles(targetIds)
      await fetchDocuments()
      deselectAll()
      const queued = result.queued ?? result.deleted
      if (queued.length) toast.info(`已提交 ${queued.length} 个文档的删除任务`)
      if (result.failed.length) toast.danger(`${result.failed.length} 个文档删除任务派发失败，请查看文档状态`)
      if (!queued.length && !result.failed.length) toast.info('没有需要删除的文档，请查看最新列表')
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
