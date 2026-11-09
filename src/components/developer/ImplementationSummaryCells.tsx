import { applicationText } from '@/lib/access'
import type { Implementation } from '@/types/developer'
import NameDescription from '@/components/common/NameDescription'
import KnowledgeUpdateBadge from './KnowledgeUpdateBadge'

export const implementationSummaryHeaders = ['实现名称', '技能类', '所属应用', '版本', '状态']
export default function ImplementationSummaryCells({ item, skillClasses, knowledgeUpdates = false }: { item: Implementation; skillClasses: { id: string; name: string }[]; knowledgeUpdates?: boolean }) {
  const color = ['已上线', '调试成功'].includes(item.status) ? 'green' : ['调试失败', '执行超时'].includes(item.status) ? 'red' : ['草稿', '已下线'].includes(item.status) ? 'neutral' : 'orange'
  return <><td className="implementation-name"><NameDescription name={item.name} description={item.description}>{knowledgeUpdates && <KnowledgeUpdateBadge skillId={item.id} count={item.knowledgeUpdateCount} />}{item.pendingChanges && <span className="status-tag orange">有编辑稿</span>}</NameDescription></td>
    <td>{skillClasses.find(row => String(row.id) === String(item.classId))?.name || item.classId}</td>
    <td>{applicationText(item)}</td><td><span className="implementation-version">{item.version || '-'}</span></td>
    <td><span className={`status-tag ${color}`}>{item.status}</span></td></>
}
