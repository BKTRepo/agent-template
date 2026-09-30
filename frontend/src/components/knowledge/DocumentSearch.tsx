import { useEffect, useMemo, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { Input } from '@heroui/react'
import { useDocumentStore } from '@/stores/documentStore'
import { StatusLabel } from './StatusLabel'

interface Props {
  /** 选中某条文档时的回调（打开文档详情） */
  onOpenDetail: (docId: string) => void
}

/**
 * 文档搜索框：按文档 ID 或文件名模糊检索。输入时下拉展示补全列表，
 * 选中后打开对应文档详情。纯前端本地检索, 无网络请求。
 */
export function DocumentSearch({ onOpenDetail }: Props) {
  const documents = useDocumentStore.use.documents()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return documents
      .filter((d) => d.filename.toLowerCase().includes(q) || d.id.toLowerCase().includes(q))
      .slice(0, 8)
  }, [query, documents])

  // 点击搜索框外部时收起下拉
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  const active = open && query.trim().length > 0

  return (
    <div ref={boxRef} className="doc-search relative w-80">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
      <Input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false)
        }}
        placeholder="搜索文档 ID / 文件名"
        aria-label="搜索文档"
        className="h-8 pl-8 text-xs"
      />

      {active && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1.5 max-h-64 overflow-auto rounded-lg border border-border bg-overlay py-1 shadow-overlay">
          {matches.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted">无匹配文档</div>
          ) : (
            matches.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => {
                  onOpenDetail(d.id)
                  setOpen(false)
                  setQuery('')
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-default"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-medium text-foreground">{d.filename}</div>
                  <div className="truncate font-mono text-[10px] text-muted">{d.id}</div>
                </div>
                <StatusLabel status={d.status} />
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
