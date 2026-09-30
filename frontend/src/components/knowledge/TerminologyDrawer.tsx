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
import { getDocumentTerminology } from '@/api/documents'
import type { Document } from '@/types/api'

interface Props {
  docId: string | null
  open: boolean
  onClose: () => void
}

/**
 * 术语对照表抽屉: 拉取后端从解析产物目录（output/rag_upload/<job_id>/terminology.md）
 * 读取的术语对照表并渲染。术语提取失败或被跳过时产物不存在, 展示空态说明。
 *
 * 渲染交由 ProgressiveMarkdown: 术语表通常为中小体量, 但超大文档（数百术语条目）
 * 同样走渐进加载, 与 Markdown 文档抽屉行为一致。
 */
export function TerminologyDrawer({ docId, open, onClose }: Props) {
  const documents = useDocumentStore.use.documents()
  const found = docId ? documents.find((d) => d.id === docId) : null

  // 关闭时 docId 立即置空, 缓存最后一次展示的文档以播放收回动画
  const [lastDoc, setLastDoc] = useState<Document | null>(null)
  useEffect(() => {
    if (found) setLastDoc(found)
  }, [found])
  const doc = found ?? lastDoc

  const [terminology, setTerminology] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !docId) return
    let cancelled = false
    setLoading(true)
    setError('')
    setTerminology(null)
    getDocumentTerminology(docId)
      .then((res) => {
        if (!cancelled) setTerminology(res.terminology ?? '')
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
              <DrawerHeading className="text-base">术语对照表</DrawerHeading>
              <DrawerCloseTrigger />
            </DrawerHeader>

            <DrawerBody>
              {/* 工具行: 文件名 + 字符数 + 复制 */}
              <div className="mb-3 flex items-center justify-between gap-2 rounded-lg bg-default/40 px-3 py-2">
                <span className="min-w-0 truncate font-mono text-xs text-muted">{doc.filename}</span>
                <span className="flex shrink-0 items-center gap-2">
                  {terminology && <span className="tabular-nums text-xs text-muted">{terminology.length.toLocaleString()} 字符</span>}
                  {terminology != null && <CopyButton text={terminology} />}
                </span>
              </div>

              {loading ? (
                <div className="flex flex-col items-center justify-center gap-2 py-20 text-muted">
                  <Loader2 className="size-6 animate-spin" />
                  <span className="text-xs">正在加载术语对照表…</span>
                </div>
              ) : error ? (
                <div className="flex flex-col items-center justify-center gap-2 py-20">
                  <FileWarning className="size-6 text-danger" />
                  <span className="text-xs text-danger">加载失败: {error}</span>
                  <Button variant="outline" size="sm" className="mt-1" onPress={() => {
                    setError('')
                    setLoading(true)
                    getDocumentTerminology(doc.id)
                      .then((res) => setTerminology(res.terminology ?? ''))
                      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
                      .finally(() => setLoading(false))
                  }}>
                    重新加载
                  </Button>
                </div>
              ) : !terminology ? (
                <div className="py-20 text-center text-xs text-muted">
                  暂无术语对照表（术语提取失败或被跳过时不生成）
                </div>
              ) : (
                <ProgressiveMarkdown markdown={terminology} />
              )}
            </DrawerBody>
          </DrawerDialog>
        </DrawerContent>
      </DrawerBackdrop>
    </Drawer>
  )
}
