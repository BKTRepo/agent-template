import { ChevronLeft, ChevronRight } from 'lucide-react'

export default function ListPagination({ total, page, pages, pageSize = 10, busy = false, label, onPageChange }: {
  total: number; page: number; pages: number; pageSize?: number; busy?: boolean; label: string; onPageChange: (page: number) => void
}) {
  const first = Math.max(1, Math.min(page - 2, pages - 4))
  const numbers = Array.from({ length: Math.min(pages, 5) }, (_, index) => first + index)
  return <div className="developer-pagination" aria-label={label}>
    <span className="pagination-total">共 {total} 条 · 每页 {pageSize} 条 · 第 {page}/{pages} 页</span>
    <button className="button small" disabled={busy || page <= 1} onClick={() => onPageChange(page - 1)}><ChevronLeft size={14} />上一页</button>
    <div className="pagination-pages">{numbers.map(number => <button key={number} className={`button small ${number === page ? 'primary' : ''}`} aria-current={number === page ? 'page' : undefined} disabled={busy} onClick={() => onPageChange(number)}>{number}</button>)}</div>
    <button className="button small" disabled={busy || page >= pages} onClick={() => onPageChange(page + 1)}>下一页<ChevronRight size={14} /></button>
  </div>
}
