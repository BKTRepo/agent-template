import { useEffect, useRef, useState } from 'react'
import Dialog from '../Dialog'
import { saveSkillClass } from '@/api/skillClasses'
import { useAccessStore } from '@/stores/accessStore'
import { useSkillClassCatalog } from '@/stores/skillClassStore'
import { hasSkillClassChanges, validateSkillClass } from '@/lib/skillClass'
import { skillAccount } from '@/api/skillSession'
import type { SkillClassDetail, SkillClassForm } from '@/types/skillClass'

export default function SkillClassFormDialog({ existing, defaultStageId, onClose, onSaved }: {
  existing?: SkillClassDetail; defaultStageId: string; onClose: () => void; onSaved: (row: SkillClassDetail) => void
}) {
  const actor = useAccessStore(state => state.actor)
  const catalog = useSkillClassCatalog()
  const [form, setForm] = useState<SkillClassForm>(() => existing ? {
    name: existing.name, test_stage_id: existing.test_stage_id || 0, description: existing.description,
    input_description: existing.input_description, output_description: existing.output_description, template: existing.template,
  } : { name: '', test_stage_id: Number(defaultStageId) || 0, description: '', input_description: '', output_description: '', template: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('')
  const changed = !existing || hasSkillClassChanges(form, existing)
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  function change<K extends keyof SkillClassForm>(field: K, value: SkillClassForm[K]) {
    setForm(previous => ({ ...previous, [field]: value })); setErrors(previous => ({ ...previous, [field]: '' })); setMessage('')
  }
  async function save() {
    if (busy) return
    if (!changed) { setMessage('内容未修改，无需保存'); return }
    const issues = validateSkillClass(form)
    setErrors(issues)
    if (Object.keys(issues).length) return
    setBusy(true); setMessage('')
    const account = skillAccount()
    try {
      const row = await saveSkillClass(form, existing)
      if (active.current && account === skillAccount()) {
        if (row.changed === false) setMessage('内容未修改，无需保存')
        else onSaved(row)
      }
    }
    catch (error) {
      if (active.current && account === skillAccount()) {
        const text = (error as Error).message; setMessage(text)
        if (text.includes('同名大类')) setErrors(previous => ({ ...previous, name: text }))
      }
    } finally { if (active.current && account === skillAccount()) setBusy(false) }
  }
  const stage = catalog.stages.find(row => Number(row.id) === form.test_stage_id)
  const fieldError = (key: string) => errors[key] && <small className="platform-field-error" role="alert">{errors[key]}</small>
  const count = (value: string, max: number, hint = '') => <small className="helper-text">{Array.from(value).length}/{max}{hint && ` · ${hint}`}</small>
  return <Dialog wide className="skill-class-form-dialog" title={existing ? '编辑技能大类' : '新建技能大类'} subtitle="大类创建即成为全平台契约，所有实现都继承它的入参与出参" busy={busy} onClose={onClose}
    footer={<><span className="helper-text skill-class-form-footer" role="status">{existing ? (!changed ? '内容未修改，无需保存' : '保存为草稿，重新发布后生效') : '创建后为「草稿」，补全契约并发布后其他团队才能引用'}</span><button className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy || !catalog.stages.length || !changed} onClick={() => void save()}>{busy ? '正在保存…' : existing ? '保存修改' : '创建大类'}</button></>}>
    <form id="skill-class-form" className="skill-class-form" onSubmit={event => { event.preventDefault(); void save() }}>
      <div className="skill-class-form-row skill-class-form-identity"><label className="form-field"><span>大类名称 <em>*</em></span><input autoFocus placeholder="如：测试环境编排" value={form.name} maxLength={20} disabled={busy} aria-invalid={!!errors.name} onChange={event => change('name', event.target.value)} />{fieldError('name')}<small className="helper-text">简洁明确，建议 4–10 个字</small></label>
        <label className="form-field"><span>维护人</span><input readOnly value={existing?.maintainer_name || actor.name || actor.id} /><small className="helper-text">契约变更与答疑由其负责</small></label></div>
      <label className="form-field"><span>测试所属阶段 <em>*</em><small>决定这个大类在测试流程中的位置</small></span><select className={!form.test_stage_id ? 'select-placeholder' : undefined} value={form.test_stage_id || ''} disabled={busy} aria-invalid={!!errors.test_stage_id} onChange={event => change('test_stage_id', Number(event.target.value))}><option value="">请选择测试所属阶段</option>{catalog.stages.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>{fieldError('test_stage_id')}<small className="helper-text">{stage?.description || '选择阶段后显示该阶段的含义'}</small></label>
      <label className="form-field"><span>功能说明 <em>*</em><small>写清能力范围、产出物形态与触发场景</small></span><textarea value={form.description} maxLength={500} disabled={busy} aria-invalid={!!errors.description} placeholder={'如：从需求文档与历史用例中提炼【系统级测试策略】，产出带 YAML frontmatter 的 Markdown 策略文件，供后续用例生成自动匹配加载。\n必须使用本技能：用户说「生成测试策略」「沉淀系统的测试套路」时调用。'} onChange={event => change('description', event.target.value)} />{count(form.description,500,'建议按「做什么 → 产出什么 → 用户会怎么说」写，括号内标注产出物')}{fieldError('description')}</label>
      <div className="skill-class-form-row"><label className="form-field"><span>输入描述 <em>*</em></span><textarea value={form.input_description} maxLength={200} disabled={busy} aria-invalid={!!errors.input_description} placeholder="按「字段 + 说明」写清需要哪些输入，如：需求描述或文档链接；接口契约与字段约束" onChange={event => change('input_description', event.target.value)} />{count(form.input_description,200,'调用方据此准备数据')}{fieldError('input_description')}</label>
        <label className="form-field"><span>输出描述 <small>选填</small></span><textarea value={form.output_description} maxLength={200} disabled={busy} aria-invalid={!!errors.output_description} placeholder="如：env[]：环境编号、服务状态、可用入口地址" onChange={event => change('output_description', event.target.value)} /><small className="helper-text">契约编辑页可补全</small>{fieldError('output_description')}</label></div>
      <label className="form-field"><span>Skill 模板 <em>*</em><small>实现类可直接套用</small></span><textarea className="skill-class-template-input" value={form.template} maxLength={100000} disabled={busy} spellCheck={false} aria-invalid={!!errors.template} placeholder="填写可供实现类套用的模板" onChange={event => change('template', event.target.value)} />{fieldError('template')}<small className="helper-text">按大类契约给出实现类骨架，团队新建实现时可参考</small></label>
      {message && <p className="error-banner" role="alert">{message}</p>}
      {catalog.error && <p className="error-banner" role="alert">{catalog.error}<button type="button" className="button small" onClick={() => void catalog.refresh().catch(() => {})}>重新加载阶段</button></p>}
    </form>
  </Dialog>
}
