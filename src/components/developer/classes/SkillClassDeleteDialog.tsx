import { AlertCircle } from 'lucide-react'
import Dialog from '../Dialog'
import type { SkillClassDetail } from '@/types/skillClass'

export default function SkillClassDeleteDialog({ row, busy, error, onClose, onConfirm }: {
  row: SkillClassDetail; busy: boolean; error: string; onClose: () => void; onConfirm: () => void
}) {
  return <Dialog title="删除技能大类" subtitle="删除后从有效大类列表移除" busy={busy} onClose={onClose}
    footer={<><button className="button" disabled={busy} onClick={onClose}>{row.can_delete ? '取消' : '关闭'}</button>{row.can_delete && <button className="button danger" disabled={busy} onClick={onConfirm}>{busy ? '正在删除…' : '确认删除'}</button>}</>}>
    <div className="skill-class-delete-warning"><AlertCircle size={22}/><div>
      <p>{row.can_delete ? '即将删除' : '暂时无法删除'} <strong>{row.name}</strong></p>
      {row.can_delete && <p>该大类下没有实现类，删除不会影响已有技能。</p>}
    </div></div>
    {(error || row.delete_disabled_reason) && <p className="error-banner" role="alert">{error || row.delete_disabled_reason}</p>}
  </Dialog>
}
