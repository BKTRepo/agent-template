import { useEffect, useState } from 'react'
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
import { FileWarning, Loader2 } from 'lucide-react'
import { CopyButton } from '@/components/common/CopyButton'
import { OverlayPressTarget } from '@/components/common/OverlayPressTarget'
import { ProgressiveMarkdown } from '@/components/knowledge/ProgressiveMarkdown'
import { useDocumentStore } from '@/stores/documentStore'
import { getDocumentMarkdown } from '@/api/documents'
import type { Document } from '@/types/api'

interface Props {
  docId: string | null
  open: boolean
  onClose: () => void
}

/**
 * Markdown 文档抽屉: 拉取后端从解析产物目录（output/rag_upload/<job_id>/<文件名>.md）
 * 读取的 markdown 全文并渲染, 供用户查看 PDF 转换效果。
 *
 * 大文档渲染交由 ProgressiveMarkdown: 首屏只渲染前几块, 滚动接近底部时渐进追加,
 * 避免一次性渲染整份大文档阻塞主线程。
 */
export function MarkdownDrawer({ docId, open, onClose }: Props) {
  const documents = useDocumentStore.use.documents()
  const found = docId ? documents.find((d) => d.id === docId) : null

  // 关闭时 docId 立即置空, 缓存最后一次展示的文档以播放收回动画
  const [lastDoc, setLastDoc] = useState<Document | null>(null)
  useEffect(() => {
    if (found) setLastDoc(found)
  }, [found])
  const doc = found ?? lastDoc

  const [markdown, setMarkdown] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !docId) return
    let cancelled = false
    setLoading(true)
    setError('')
    setMarkdown(null)
    getDocumentMarkdown(docId)
      .then((res) => {
        if (!cancelled) setMarkdown(res.markdown ?? '')
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, docId])

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
          <DrawerDialog className="sm:w-[42rem]">
            <DrawerHeader>
              <DrawerHeading className="text-base">Markdown 文档</DrawerHeading>
              <DrawerCloseTrigger />
            </DrawerHeader>

            <DrawerBody>
              {/* 工具行: 文件名 + 字符数 + 复制 */}
              <div className="mb-3 flex items-center justify-between gap-2 rounded-lg bg-default/40 px-3 py-2">
                <span className="min-w-0 truncate font-mono text-xs text-muted">{doc.filename}</span>
                <span className="flex shrink-0 items-center gap-2">
                  {markdown && <span className="tabular-nums text-xs text-muted">{markdown.length.toLocaleString()} 字符</span>}
                  {markdown != null && <CopyButton text={markdown} />}
                </span>
              </div>

              {loading ? (
                <div className="flex flex-col items-center justify-center gap-2 py-20 text-muted">
                  <Loader2 className="size-6 animate-spin" />
                  <span className="text-xs">正在加载 Markdown…</span>
                </div>
              ) : error ? (
                <div className="flex flex-col items-center justify-center gap-2 py-20">
                  <FileWarning className="size-6 text-danger" />
                  <span className="text-xs text-danger">加载失败: {error}</span>
                  <Button variant="outline" size="sm" className="mt-1" onPress={() => {
                    setError('')
                    setLoading(true)
                    getDocumentMarkdown(doc.id)
                      .then((res) => setMarkdown(res.markdown ?? ''))
                      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
                      .finally(() => setLoading(false))
                  }}>
                    重新加载
                  </Button>
                </div>
              ) : !markdown ? (
                <div className="py-20 text-center text-xs text-muted">
                  暂无 Markdown 内容（文档可能尚未完成解析）
                </div>
              ) : (
                <ProgressiveMarkdown markdown={markdown} />
              )}
            </DrawerBody>
          </DrawerDialog>
        </DrawerContent>
      </DrawerBackdrop>
    </Drawer>
  )
}
