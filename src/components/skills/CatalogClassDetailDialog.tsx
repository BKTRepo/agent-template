import { useState } from 'react'
import Dialog from '@/components/developer/Dialog'
import TestStageBadge from './TestStageBadge'
import { downloadBlob } from '@/lib/resourceStorage'
import { copyText } from '@/lib/clipboard'
import type { ClassDefinition } from '@/api/skillCatalog'

export default function CatalogClassDetailDialog({ row, onClose }: { row: ClassDefinition; onClose: () => void }) {
  const [copied, setCopied] = useState('')
  return <Dialog wide className="skill-class-catalog-detail" title="技能类详情" onClose={onClose} footer={<><button className="button" onClick={onClose}>关闭</button><button className="button primary" disabled={!row.template} onClick={() => downloadBlob(new Blob([row.template!], {type:'text/plain;charset=utf-8'}), `${row.name.replace(/[\\/<>:"|?*]/g,'_')}-Skill模板.md`)}>下载模板</button></>}>
    <h2>{row.name}</h2><p className="helper-text">统一输入、输出规定与 Skill 契约。</p>
    <dl className="skill-class-contract"><div><dt>输入规定</dt><dd>{row.input_description || (row.input_schema ? JSON.stringify(row.input_schema,null,2) : '未配置')}</dd></div><div><dt>输出规定</dt><dd>{row.output_description || (row.output_schema ? JSON.stringify(row.output_schema,null,2) : '未配置')}</dd></div></dl>
    <section className="skill-class-description-block"><h3>功能说明 <TestStageBadge name={row.test_stage_name} code={row.test_stage_code} /></h3><p>{row.description || '未配置'}</p></section>
    <section className="skill-class-description-block"><h3>Skill 模板 <span className="status-tag neutral">可直接套用</span></h3><div className="skill-class-template-preview"><button className="button small" disabled={!row.template} onClick={() => void copyText(row.template || '').then(ok => setCopied(ok ? '已复制' : '复制失败，请手动选择复制'))}>复制</button><pre>{row.template || '未配置'}</pre></div>{copied && <p role="status" className="helper-text">{copied}</p>}</section>
  </Dialog>
}
