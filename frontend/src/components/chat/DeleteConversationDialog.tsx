import { Button } from '@heroui/react'
import { Trash2 } from 'lucide-react'
import { AppModal } from '@/components/common/Modal'
import type { Conversation } from '@/types/api'

interface Props {
  conversation: Conversation | null
  onClose: () => void
  onConfirm: () => void
}

/** 删除对话确认弹窗——形式与知识库 ClearDialog 一致, 无需输入 YES */
export function DeleteConversationDialog({ conversation, onClose, onConfirm }: Props) {
  return (
    <AppModal
      open={conversation !== null}
      onClose={onClose}
      size="sm"
      title={
        <span className="flex items-center gap-2 text-danger">
          <Trash2 className="h-5 w-5" />
          删除对话
        </span>
      }
      description="该对话将被永久删除，此操作无法恢复。"
      footer={
        <>
          <Button variant="outline" onPress={onClose}>取消</Button>
          <Button variant="danger" onPress={onConfirm}>
            <Trash2 className="size-4" /> 删除
          </Button>
        </>
      }
    >
      <span className="sr-only">确认删除对话</span>
    </AppModal>
  )
}
