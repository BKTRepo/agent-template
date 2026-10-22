import { nextVersion } from '@/lib/version'
import type { ImplementationForm } from '@/types/developer'
import ApplicationPicker from './ApplicationPicker'
import KnowledgePicker from './KnowledgePicker'
import ResourceUpload from './ResourceUpload'

export default function SkillFields({ form, update, skillClasses = [], applications = [], errors = {}, disabled = false, editing = false, activeIds = [], onAdd = () => {}, onRemove = () => {} }: { form: ImplementationForm; update: <K extends keyof ImplementationForm>(key: K, value: ImplementationForm[K]) => void; skillClasses?: { id: string; name: string }[]; applications?: { id: string; name: string }[]; errors?: Record<string, string>; disabled?: boolean; editing?: boolean; activeIds?: string[]; onAdd?: (files: File[]) => void; onRemove?: (id: string) => void }) {
  const error = (key: string) => errors[key] && <span role="alert" className="field-error">{errors[key]}</span>
  let next = '1.0.0'
  try { if (editing) next = nextVersion(form.version) } catch { next = '待系统校正历史版本' }
  return <fieldset className="implementation-form skill-create-form" disabled={disabled}>
    <label data-skill-field="classId" className="form-field"><span>所属技能大类 <em>*</em></span><select value={form.classId} aria-invalid={!!errors.classId} onChange={event => update('classId', event.target.value)}><option value="">请选择所属技能大类</option>{skillClasses.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>{error('classId')}</label>
    <label data-skill-field="name" className="form-field"><span>技能名称 <em>*</em></span><input maxLength={128} value={form.name} placeholder="请输入技能名称，如：核心系统用例生成" aria-invalid={!!errors.name} onChange={event => update('name', event.target.value)} />{error('name')}<p className="helper-text">名称唯一，不可与已有技能重复</p></label>
    <label data-skill-field="description" className="form-field"><span>描述 <em>*</em></span><textarea aria-label="描述" maxLength={1024} value={form.description} placeholder="一句话描述该技能的能力与适用场景" aria-invalid={!!errors.description} onChange={event => update('description', event.target.value)} />{error('description')}</label>
    <div className="form-field"><span>版本</span><p className="form-hint" aria-label="系统版本">{editing ? `当前版本 ${form.version}${disabled ? '（只读）' : `；保存修改后自动递增为 ${next}`}` : '系统自动生成：初始 1.0.0，每次保存修改后自动递增，无需手填。'}</p></div>
    <div data-skill-field="applicationIds" tabIndex={-1}><ApplicationPicker value={form.applicationIds} options={applications} disabled={disabled} onChange={ids => update('applicationIds', ids)} /></div>{error('applicationIds')}
    <label data-skill-field="instructions" className="form-field"><span>执行指令 <em>*</em></span><textarea className="instructions-input" value={form.instructions} maxLength={100000} placeholder="填写具体执行步骤、业务约束、输入输出要求等" aria-invalid={!!errors.instructions} onChange={event => update('instructions', event.target.value)} />{error('instructions')}</label>
    <div data-skill-field="resourceIds" tabIndex={-1}><KnowledgePicker team="" selected={form.knowledgeBases ?? []} disabled={disabled} onChange={items => { update('knowledgeBases', items); update('resourceIds', items.map(row => row.id)) }} /></div>{error('resourceIds')}
    <div data-skill-field="uploadedResources" tabIndex={-1}><ResourceUpload items={form.uploadedResources ?? []} activeIds={disabled ? form.uploadedResources?.map(row => row.id) ?? [] : activeIds} disabled={disabled} error={errors.uploadedResources} onAdd={onAdd} onRemove={onRemove} onCategory={(id, category) => update('uploadedResources', form.uploadedResources?.map(row => row.id === id ? { ...row, category } : row) ?? [])} /></div>
    <label data-skill-field="resourceUsage" className="form-field"><span>资源使用说明 {(!!form.resourceIds.length || !!form.uploadedResources?.length) && <em>*</em>}</span><textarea value={form.resourceUsage ?? ''} maxLength={10000} placeholder="描述资源什么时候使用、用来做什么" aria-invalid={!!errors.resourceUsage} onChange={event => update('resourceUsage', event.target.value)} />{error('resourceUsage')}</label>
    <label data-skill-field="compatibility" className="form-field"><span>运行环境要求</span><textarea aria-invalid={!!errors.compatibility} maxLength={500} value={form.compatibility ?? ''} placeholder="描述依赖包、生成脚本语言、运行时版本等" onChange={event => update('compatibility', event.target.value)} />{error('compatibility')}</label>
    {form.skillMarkdown && <details><summary>已保存的 Skill 定义（Markdown）</summary><pre className="markdown-preview">{form.skillMarkdown}</pre></details>}
  </fieldset>
}
