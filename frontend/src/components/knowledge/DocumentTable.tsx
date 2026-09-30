import { useState } from 'react'
import {
  Table,
  TableScrollContainer,
  TableContent,
  TableHeader,
  TableColumn,
  TableBody,
  TableRow,
  TableCell,
  Button,
  Pagination,
  Tooltip,
} from '@heroui/react'
import { AlignLeft, BookOpenText, FileText, FileUp, History, Layers, RotateCw } from 'lucide-react'
import { toast } from '@/lib/toast'
import { CheckboxField } from '@/components/common/CheckboxField'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { EmptyState } from '@/components/common/EmptyState'
import { StatusLabel } from './StatusLabel'
import { useDocumentStore } from '@/stores/documentStore'
import { retryDocument } from '@/api/convert'
import type { Document, DocumentStatus } from '@/types/api'

const PAGE_SIZE = 5

const ACTIVE_STATUSES: DocumentStatus[] = ['splitting', 'parsing', 'terminology', 'analyzing', 'chunking', 'embedding']

/** 生成分页页码列表，中间页码围绕当前页，两侧超出时以省略号占位 */
function getPageItems(current: number, total: number): (number | 'ellipsis-l' | 'ellipsis-r')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const items: (number | 'ellipsis-l' | 'ellipsis-r')[] = [1]
  const start = Math.max(2, current - 1)
  const end = Math.min(total - 1, current + 1)
  if (start > 2) items.push('ellipsis-l')
  for (let i = start; i <= end; i++) items.push(i)
  if (end < total - 1) items.push('ellipsis-r')
  items.push(total)
  return items
}

/** 文件类型徽标: 空心彩色边框长方形 + 大写字母（P=PDF 红 / D=Word 蓝 / T=纯文本 琥珀） */
function FileTypeBadge({ filename }: { filename: string }) {
  const base = 'flex h-6 w-5 shrink-0 items-center justify-center rounded border-2 bg-transparent text-[10px] font-bold'
  const ext = filename.includes('.') ? filename.slice(filename.lastIndexOf('.') + 1).toLowerCase() : ''
  if (ext === 'pdf') return <span className={`${base} border-red-500 text-red-500`}>P</span>
  if (ext === 'doc' || ext === 'docx') return <span className={`${base} border-blue-500 text-blue-500`}>D</span>
  if (ext === 'txt' || ext === 'md') return <span className={`${base} border-amber-500 text-amber-500`}>T</span>
  return <span className={`${base} border-zinc-500 text-zinc-500`}>{ext ? ext[0]!.toUpperCase() : 'F'}</span>
}

const STATUS_BAR_COLORS: Record<string, string> = {
  splitting: '#06b6d4',
  parsing: '#06b6d4',
  terminology: '#f97316',
  analyzing: '#a855f7',
  chunking: '#6366f1',
  embedding: '#f59e0b',
}
function _barColor(status: string): string {
  return STATUS_BAR_COLORS[status] || '#3b82f6'
}

interface Props {
  onOpenDetail: (docId: string) => void
  /** 查看 Markdown 文档 */
  onOpenMarkdown?: (docId: string) => void
  /** 查看术语对照表 */
  onOpenTerminology?: (docId: string) => void
  /** 查看分块结果 */
  onOpenChunks?: (docId: string) => void
  /** 增量更新（complete / failed 文档可用） */
  onOpenUpdate?: (docId: string) => void
  /** 回滚到上一版本（failed 且 rollback_available 可用） */
  onOpenRollback?: (docId: string) => void
}

export function DocumentTable({ onOpenDetail, onOpenMarkdown, onOpenTerminology, onOpenChunks, onOpenUpdate, onOpenRollback }: Props) {
  const documents = useDocumentStore.use.documents()
  const loading = useDocumentStore.use.loading()
  const selectedIds = useDocumentStore.use.selectedIds()
  const toggleSelect = useDocumentStore.use.toggleSelect()
  const updateDocument = useDocumentStore.use.updateDocument()
  const startPolling = useDocumentStore.use.startPolling()
  const [page, setPage] = useState(1)

  const totalPages = Math.max(1, Math.ceil(documents.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageDocs = documents.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  const handleRetry = async (doc: Document) => {
    try {
      await retryDocument(doc.id)
      updateDocument(doc.id, {
        status: 'parsing', summary: '-', error_msg: '', error_trace: '',
        // 与后端重试逻辑一致: 不清空各阶段计时——已成功阶段保留上一轮计时,
        // 被重跑的阶段（失败阶段及其后续）随执行覆写为新计时
      })
      startPolling(doc.id)
      toast.success(`已提交重试: ${doc.filename}`)
    } catch (err) {
      toast.danger(`重试失败: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  if (loading) return <LoadingSpinner />
  if (documents.length === 0) {
    return <EmptyState icon="📂" title="暂无文档" description="点击「上传」按钮开始构建知识库" />
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <Table className="doc-table">
        <TableScrollContainer>
          <TableContent aria-label="文档列表">
            <TableHeader>
              <TableColumn id="select" className="w-[5%] text-center">选择</TableColumn>
              <TableColumn id="filename" isRowHeader className="w-[17%]">文件名 / ID</TableColumn>
              <TableColumn id="summary" className="w-[15%]">摘要</TableColumn>
              <TableColumn id="status" className="w-[15%]">状态</TableColumn>
              <TableColumn id="length" className="w-[8%]">长度</TableColumn>
              <TableColumn id="chunks" className="w-[9%]">分块</TableColumn>
              <TableColumn id="created" className="w-[10%]">创建时间</TableColumn>
              <TableColumn id="updated" className="w-[10%]">更新时间</TableColumn>
              <TableColumn id="actions" className="w-[11%] text-center">动作</TableColumn>
            </TableHeader>
            <TableBody>
              {pageDocs.map((doc) => (
                <TableRow key={doc.id} id={doc.id}>
                  <TableCell>
                    <div className="flex justify-center">
                      <CheckboxField isSelected={selectedIds.has(doc.id)} onChange={() => toggleSelect(doc.id)} />
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <FileTypeBadge filename={doc.filename} />
                      <div className="min-w-0">
                        <div className="max-w-[250px] truncate text-sm font-medium text-foreground">{doc.filename}</div>
                        <div className="truncate font-mono text-xs text-muted">{doc.id}</div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="max-w-[180px] truncate text-sm text-muted">
                      {(doc.summary || '-').replace(/\n/g, ' ').slice(0, 80)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-1.5">
                        <StatusLabel status={doc.status} />
                        {(doc.status === 'splitting' || doc.status === 'parsing') && doc.total_parts > 1 && (
                          <span className="text-xs text-muted">({doc.completed_parts}/{doc.total_parts})</span>
                        )}
                        {doc.status === 'terminology' && doc.terminology_total_batches > 1 && (
                          <span className="text-xs text-muted">
                            ({doc.terminology_completed_batches}/{doc.terminology_total_batches})
                          </span>
                        )}
                      </div>
                      {doc.is_updating && (
                        <span className="text-xs text-muted">
                          {doc.status === 'failed' ? '更新失败 · 问答仍用旧版本' : '更新中 · 问答仍用旧版本'}
                        </span>
                      )}
                      {ACTIVE_STATUSES.includes(doc.status) && (
                        <div className="h-1.5 w-full overflow-hidden rounded-full bg-default">
                          {(doc.status === 'splitting' || doc.status === 'parsing') && doc.total_parts > 1 ? (
                            <div
                              className="h-full rounded-full bg-cyan-500 transition-all duration-500"
                              style={{ width: `${(doc.completed_parts / doc.total_parts) * 100}%` }}
                            />
                          ) : doc.status === 'terminology' && doc.terminology_total_batches > 1 ? (
                            <div
                              className="h-full rounded-full bg-orange-500 transition-all duration-500"
                              style={{ width: `${(doc.terminology_completed_batches / doc.terminology_total_batches) * 100}%` }}
                            />
                          ) : (
                            <div className="animate-indeterminate" style={{ background: _barColor(doc.status) }} />
                          )}
                        </div>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="tabular-nums text-muted">
                    {doc.content_length != null ? doc.content_length.toLocaleString() : '-'}
                  </TableCell>
                  <TableCell className="tabular-nums text-muted">
                    {doc.chunks_count ?? '-'}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs text-muted">
                    {doc.created_at ? new Date(doc.created_at).toLocaleString() : '-'}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs text-muted">
                    {doc.updated_at ? new Date(doc.updated_at).toLocaleString() : '-'}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-center gap-0.5">
                      <Tooltip>
                        <Tooltip.Trigger>
                          <Button
                            variant="ghost"
                            size="sm"
                            isIconOnly
                            className="size-7"
                            aria-label="查看详情"
                            onPress={() => onOpenDetail(doc.id)}
                          >
                            <AlignLeft className="size-3.5 text-muted" />
                          </Button>
                        </Tooltip.Trigger>
                        <Tooltip.Content>查看详情</Tooltip.Content>
                      </Tooltip>
                      {doc.status === 'failed' && (
                        <Tooltip>
                          <Tooltip.Trigger>
                            <Button
                              variant="ghost"
                              size="sm"
                              isIconOnly
                              className="size-7"
                              aria-label="重试"
                              onPress={() => handleRetry(doc)}
                            >
                              <RotateCw className="size-3.5 text-accent" />
                            </Button>
                          </Tooltip.Trigger>
                          <Tooltip.Content>重试</Tooltip.Content>
                        </Tooltip>
                      )}
                      {doc.status === 'failed' && doc.rollback_available && (
                        <Tooltip>
                          <Tooltip.Trigger>
                            <Button
                              variant="ghost"
                              size="sm"
                              isIconOnly
                              className="size-7"
                              aria-label="回滚到上一版本"
                              onPress={() => onOpenRollback?.(doc.id)}
                            >
                              <History className="size-3.5 text-warning" />
                            </Button>
                          </Tooltip.Trigger>
                          <Tooltip.Content>回滚到上一版本</Tooltip.Content>
                        </Tooltip>
                      )}
                      {doc.status === 'complete' && (
                        <>
                          <Tooltip>
                            <Tooltip.Trigger>
                              <Button
                                variant="ghost"
                                size="sm"
                                isIconOnly
                                className="size-7"
                                aria-label="查看 Markdown 文档"
                                onPress={() => onOpenMarkdown?.(doc.id)}
                              >
                                <FileText className="size-3.5 text-muted" />
                              </Button>
                            </Tooltip.Trigger>
                            <Tooltip.Content>查看 Markdown 文档</Tooltip.Content>
                          </Tooltip>
                          <Tooltip>
                            <Tooltip.Trigger>
                              <Button
                                variant="ghost"
                                size="sm"
                                isIconOnly
                                className="size-7"
                                aria-label="查看术语对照表"
                                onPress={() => onOpenTerminology?.(doc.id)}
                              >
                                <BookOpenText className="size-3.5 text-muted" />
                              </Button>
                            </Tooltip.Trigger>
                            <Tooltip.Content>查看术语对照表</Tooltip.Content>
                          </Tooltip>
                          <Tooltip>
                            <Tooltip.Trigger>
                              <Button
                                variant="ghost"
                                size="sm"
                                isIconOnly
                                className="size-7"
                                aria-label="查看分块结果"
                                onPress={() => onOpenChunks?.(doc.id)}
                              >
                                <Layers className="size-3.5 text-muted" />
                              </Button>
                            </Tooltip.Trigger>
                            <Tooltip.Content>查看分块结果</Tooltip.Content>
                          </Tooltip>
                        </>
                      )}
                      {doc.status === 'complete' && (
                        <Tooltip>
                          <Tooltip.Trigger>
                            <Button
                              variant="ghost"
                              size="sm"
                              isIconOnly
                              className="size-7"
                              aria-label="增量更新"
                              onPress={() => onOpenUpdate?.(doc.id)}
                            >
                              <FileUp className="size-3.5 text-accent" />
                            </Button>
                          </Tooltip.Trigger>
                          <Tooltip.Content>增量更新</Tooltip.Content>
                        </Tooltip>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </TableContent>
        </TableScrollContainer>
      </Table>

      <div className="mt-auto flex items-center justify-between border-t border-border px-1 pt-3">
        <span className="text-xs text-muted">
          共 {documents.length} 个文档 · 第 {currentPage} / {totalPages} 页
        </span>
        <Pagination size="sm" className="w-auto">
          <Pagination.Previous isDisabled={currentPage === 1} onPress={() => setPage(currentPage - 1)}>
            <Pagination.PreviousIcon />
          </Pagination.Previous>
          <Pagination.Content>
            {getPageItems(currentPage, totalPages).map((item) =>
              typeof item === 'number' ? (
                <Pagination.Item key={item}>
                  <Pagination.Link isActive={item === currentPage} onPress={() => setPage(item)}>
                    {item}
                  </Pagination.Link>
                </Pagination.Item>
              ) : (
                <Pagination.Item key={item}>
                  <Pagination.Ellipsis />
                </Pagination.Item>
              ),
            )}
          </Pagination.Content>
          <Pagination.Next isDisabled={currentPage === totalPages} onPress={() => setPage(currentPage + 1)}>
            <Pagination.NextIcon />
          </Pagination.Next>
        </Pagination>
      </div>
    </div>
  )
}
