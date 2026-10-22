import type { KnowledgeBase } from '@/types/developer'
export default function KnowledgeHistory({ item }: { item?: KnowledgeBase }) {
  if (!item) return null
  return <section className="knowledge-history"><h3>编辑历史</h3><div className="implementation-table-wrap"><table className="implementation-table"><thead><tr><th>版本号</th><th>维护人</th><th>变更描述</th></tr></thead><tbody>{item.history?.map(row => <tr key={row.id}><td>{row.version}</td><td>{row.maintainer}</td><td>{row.summary}</td></tr>)}{!item.history?.length && <tr><td colSpan={3}>暂无历史记录，后续编辑保存时开始记录。</td></tr>}</tbody></table></div></section>
}
