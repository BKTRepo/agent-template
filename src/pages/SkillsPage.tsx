import { useState } from 'react'
import { ChevronDown, Download, Sparkles } from 'lucide-react'
import Dialog from '@/components/developer/Dialog'
import DebugDialog from '@/components/developer/DebugDialog'
import SkillFields from '@/components/developer/SkillFields'
import SearchSelect from '@/components/developer/SearchSelect'
import { skillContract } from '@/lib/skillContract'
import { downloadBlob } from '@/lib/resourceStorage'
import { downloadSkillArchive } from '@/api/skillArchive'
import { useDeveloperStore } from '@/stores/developerStore'
import { skillClasses } from '@/mocks/developerData'
import { skillCatalog } from '@/lib/skillCatalog'
import { applicationText, applications } from '@/lib/access'
import type { Implementation } from '@/types/developer'

const emptyFilters = { name: '', classId: '', system: '', maintainer: '' }
export default function SkillsPage() {
  const implementations = useDeveloperStore(state => state.implementations)
  const [filters, setFilters] = useState(emptyFilters)
  const [applied, setApplied] = useState(emptyFilters)
  const [expanded, setExpanded] = useState(['SKILL-CASE-001'])
  const [detail, setDetail] = useState<Implementation | null>(null)
  const [classDetail, setClassDetail] = useState<string>()
  const [debugItem, setDebugItem] = useState<Implementation | null>(null)
  const [busy, setBusy] = useState<string>()
  const [error, setError] = useState('')
  const rows = skillCatalog(implementations)
  const maintainer = (item: Implementation) => item.creatorName || '历史维护人'
  const filtered = rows.filter(item => `${item.name} ${skillClasses.find(row => row.id === item.classId)?.name}`.toLowerCase().includes(applied.name.trim().toLowerCase()) && (!applied.classId || applied.classId === item.classId) && (!applied.system || (item.applicationIds ?? [item.system]).some(id => id === '*' || id === applied.system)) && (!applied.maintainer || applied.maintainer === maintainer(item)))
  async function download(item: Implementation) {
    setBusy(item.id); setError('')
    try { await downloadSkillArchive(item) } catch (error) { setError((error as Error).message) } finally { setBusy(undefined) }
  }
  return <>
    <div className="page-heading"><div><h1>技能中心</h1><p>Skill 类 + 实现类管理 · 技能按大类展示 · 已上线可在线测试，已下线保留详情和下载</p></div></div>
    <form className="surface catalog-filters" onSubmit={event => { event.preventDefault(); setApplied(filters); setExpanded(skillClasses.map(row => row.id)) }}>
      <input aria-label="技能名称模糊搜索" placeholder="名称模糊搜索" value={filters.name} onChange={event => setFilters(previous => ({ ...previous, name: event.target.value }))} />
      <select aria-label="技能类" value={filters.classId} onChange={event => setFilters(previous => ({ ...previous, classId: event.target.value }))}><option value="">全部技能大类</option>{skillClasses.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
      <SearchSelect label="筛选所属应用" value={filters.system} options={applications} placeholder="全部应用" onChange={value => setFilters(previous => ({ ...previous, system: value }))} />
      <SearchSelect label="维护人" value={filters.maintainer} options={[...new Set(rows.map(maintainer))].map(name => ({ id: name, name }))} placeholder="全部维护人" onChange={value => setFilters(previous => ({ ...previous, maintainer: value }))} />
      <button className="button primary">搜索</button><button type="button" className="button" onClick={() => { setFilters(emptyFilters); setApplied(emptyFilters); setExpanded(['SKILL-CASE-001']) }}>重置</button>
    </form>
    <button className="button" onClick={() => setExpanded(expanded.length === skillClasses.length ? [] : skillClasses.map(row => row.id))}>{expanded.length === skillClasses.length ? '收起所有技能' : '展开所有技能'}</button>
    {error && <p className="error-banner" role="alert">{error}</p>}
    <div className="skill-group-list">{skillClasses.filter(row => (!applied.classId || row.id === applied.classId) && (!applied.name.trim() || row.name.includes(applied.name.trim()) || filtered.some(item => item.classId === row.id))).map(skillClass => {
      const items = filtered.filter(row => row.classId === skillClass.id)
      return <section className="surface skill-group" key={skillClass.id}><div className="skill-group-heading"><Sparkles size={22} /><div><h2><button className="skill-class-title" onClick={() => setExpanded(old => old.includes(skillClass.id) ? old.filter(id => id !== skillClass.id) : [...old, skillClass.id])}>{skillClass.name}</button> <small>{skillClass.id}</small></h2><p>{skillClass.description || (skillClass.id === 'SKILL-CASE-001' ? '根据需求、接口契约与测试规范自动生成结构化测试用例' : '按统一 Skill 契约提供测试辅助能力')}</p></div><span className="status-tag neutral">{items.length} 个实现</span><span className="status-tag green">已启用</span><button className="button small" onClick={() => setClassDetail(skillClass.id)}>类详情</button><button className="icon-button" aria-label={`${expanded.includes(skillClass.id) ? '收起' : '展开'} ${skillClass.name}`} onClick={() => setExpanded(previous => previous.includes(skillClass.id) ? previous.filter(id => id !== skillClass.id) : [...previous, skillClass.id])}><ChevronDown size={18} /></button></div>
        {expanded.includes(skillClass.id) && <div className="implementation-table-wrap"><table className="implementation-table"><thead><tr>{['实现名称', '所属应用', '维护人', '版本', '调用次数', '状态', '操作'].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{items.map(item => <tr key={item.id}><td className="implementation-name">{item.name}<span className="status-tag neutral">{item.buildOrigin === 'backend' ? '后端构建' : '示例'}</span></td><td>{applicationText(item)}</td><td>{maintainer(item)}</td><td>{item.version}</td><td>—</td><td><span className={`status-tag ${item.status === '已上线' ? 'green' : 'neutral'}`}>{item.status}</span></td><td><div className="table-actions"><button className="button small" onClick={() => setDetail(item)}>详情</button><button className="button small" disabled={item.status === '已下线'} onClick={() => setDebugItem({ ...item, buildId: item.buildId ?? `catalog-${item.id}-${item.version}` })}>在线测试</button><button className="button small" disabled={!!busy} onClick={() => download(item)}><Download size={13} />{busy === item.id ? '打包中…' : '下载技能'}</button></div></td></tr>)}{!items.length && <tr><td className="empty-table" colSpan={7}>暂无符合条件的已上线实现类</td></tr>}</tbody></table></div>}
      </section>
    })}</div>
    <p className="demo-note">示例下载为实际 ZIP，包含 SKILL.md、全部挂载知识库文件和上传资源。示例知识内容与执行结果用于演示；真实包通过后端下载接口获取。</p>
    {detail && <Dialog title={`实现类详情 · ${detail.name}`} onClose={() => setDetail(null)} footer={<><button className="button" onClick={() => setDetail(null)}>关闭</button><button className="button primary" disabled={!!busy} onClick={() => download(detail)}>下载技能 ZIP</button></>}><SkillFields form={detail} update={() => {}} editing disabled />{error && <p className="error-banner">{error}</p>}</Dialog>}
    {classDetail && (() => { const kind = skillClasses.find(row => row.id === classDetail)!; const contract = skillContract({ id: kind.id, name: kind.name, classId: kind.id, description: kind.description ?? '' }); return <Dialog title="技能大类详情" onClose={() => setClassDetail(undefined)} footer={<><button className="button" onClick={() => setClassDetail(undefined)}>关闭</button><button className="button primary" onClick={() => downloadBlob(new Blob([`---\nname: skill-template\ndescription: ${JSON.stringify(kind.name)}\nversion: "1.0.0"\n---\n\n# ${kind.name}\n\n## 输入\n${contract.input}\n\n## 输出\n${contract.output}\n\n## 执行步骤\n1. 校验输入。\n2. 检索挂载知识库。\n3. 按输出契约生成结果。\n`], { type: 'text/markdown' }), `${kind.name}-Skill模板.md`)}>下载模板</button></>}><h3>{kind.name} · {kind.id}</h3><dl className="constraint-details">{[['输入 Schema',contract.input],['输出 Schema',contract.output],['类通识知识库','用例设计规范、测试工艺规范（自动继承 · 示例）']].map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><h3>Skill 模板</h3><pre className="markdown-preview">{`# ${kind.name}\n输入标准 → 检索知识 → 生成输出 → 校验结果`}</pre></Dialog> })()} 
    {debugItem && <DebugDialog key={debugItem.id} item={debugItem} onClose={() => setDebugItem(null)} onResult={debug => setDebugItem(previous => previous ? { ...previous, debug } : previous)} />}
  </>
}
