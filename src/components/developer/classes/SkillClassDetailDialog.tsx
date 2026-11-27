import Dialog from '../Dialog'
import TestStageBadge from '@/components/skills/TestStageBadge'
import type { SkillClassDetail } from '@/types/skillClass'

const contract = (description: string, schema: unknown) => description || (schema ? JSON.stringify(schema, null, 2) : '未填写')
export default function SkillClassDetailDialog({ row, onClose, onEdit, busy = false, error = '' }: {
  row: SkillClassDetail; onClose: () => void; onEdit: () => void; busy?: boolean; error?: string
}) {
  return <Dialog wide className="skill-class-management-detail" title={row.name} busy={busy} onClose={onClose}
    footer={<><span className="helper-text">{row.publication_status==='PUBLISHED'?'修改保存为草稿，重新发布后生效':'草稿可查看，发布后才能用于新建实现'}</span><button className="button" disabled={busy} onClick={onClose}>关闭</button>{row.can_edit && <button className="button" disabled={busy} onClick={onEdit}>编辑</button>}</>}>
    <dl className="skill-class-meta"><div><dt>发布状态</dt><dd>{row.publication_status==='PUBLISHED'&&!row.has_unpublished_changes?'已发布':'草稿'}</dd></div><div><dt>测试阶段</dt><dd><TestStageBadge name={row.test_stage_name} code={row.test_stage_code} /></dd></div><div><dt>维护人</dt><dd>{row.maintainer_name}</dd></div><div><dt>实现数</dt><dd>{row.implementation_count} 个</dd></div><div><dt>更新时间</dt><dd>{row.updated_time ? new Date(row.updated_time).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'}) : '历史记录未提供'}</dd></div></dl>
    {error&&<p className="error-banner" role="alert">{error}</p>}
    <section className="skill-class-description-block"><h3>功能说明</h3><p>{row.description || '未填写'}</p></section>
    <section className="skill-class-description-block"><h3>输入描述</h3><pre>{contract(row.input_description,row.input_schema)}</pre></section>
    <section className="skill-class-description-block"><h3>输出描述</h3><pre>{contract(row.output_description,row.output_schema)}</pre></section>
    <p className="skill-class-permission-note">{row.can_edit ? '你是该大类的维护人，可以编辑。' : `该大类由 ${row.maintainer_name} 维护，你只能查看。`}</p>
  </Dialog>
}
