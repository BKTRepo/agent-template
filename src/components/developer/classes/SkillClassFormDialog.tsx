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
  const count = (value: string, max: number) => <small className="helper-text">{Array.from(value).length}/{max}</small>
  return <Dialog wide className="skill-class-form-dialog" title={existing ? '编辑技能大类' : '新建技能大类'} subtitle="保存为草稿，所有用户可查看；发布后才能用于新建实现" busy={busy} onClose={onClose}
    footer={<>{existing&&!changed&&<span className="helper-text" role="status">内容未修改，无需保存</span>}<button className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy || !catalog.stages.length || !changed} onClick={() => void save()}>{busy ? '正在保存…' : existing ? '保存修改' : '创建大类'}</button></>}>
    <form id="skill-class-form" className="skill-class-form" onSubmit={event => { event.preventDefault(); void save() }}>
      <div className="skill-class-form-row"><label className="form-field"><span>大类名称 <em>*</em></span><input autoFocus value={form.name} maxLength={20} disabled={busy} aria-invalid={!!errors.name} onChange={event => change('name', event.target.value)} />{fieldError('name')}<small className="helper-text">简洁明确，最多20字，同名大类不可重复创建</small></label>
        <label className="form-field"><span>维护人</span><input readOnly value={existing?.maintainer_name || actor.name || actor.id} /><small className="helper-text">固定为创建人，不可修改</small></label></div>
      <label className="form-field"><span>测试所属阶段 <em>*</em></span><select value={form.test_stage_id || ''} disabled={busy} aria-invalid={!!errors.test_stage_id} onChange={event => change('test_stage_id', Number(event.target.value))}><option value="">请选择测试所属阶段</option>{catalog.stages.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>{fieldError('test_stage_id')}<small className="helper-text">{stage?.description || '选择阶段后显示该阶段的含义'}</small></label>
      <label className="form-field"><span>功能说明 <em>*</em></span><textarea value={form.description} maxLength={500} disabled={busy} aria-invalid={!!errors.description} placeholder="写清做什么、产出什么、用户会怎么说；产出物用【】标注，并说明必须使用本技能的场景" onChange={event => change('description', event.target.value)} />{count(form.description,500)}{fieldError('description')}</label>
      <div className="skill-class-form-row"><label className="form-field"><span>输入描述 <em>*</em></span><textarea value={form.input_description} maxLength={200} disabled={busy} aria-invalid={!!errors.input_description} placeholder="说明需要哪些输入，调用方据此准备数据" onChange={event => change('input_description', event.target.value)} />{count(form.input_description,200)}{fieldError('input_description')}</label>
        <label className="form-field"><span>输出描述 <small>发布前必填</small></span><textarea value={form.output_description} maxLength={200} disabled={busy} aria-invalid={!!errors.output_description} placeholder="说明输出内容及结构" onChange={event => change('output_description', event.target.value)} />{count(form.output_description,200)}{fieldError('output_description')}</label></div>
      <label className="form-field"><span>Skill 模板 <em>*</em></span><textarea className="skill-class-template-input" value={form.template} maxLength={100000} disabled={busy} spellCheck={false} aria-invalid={!!errors.template} placeholder="# 执行步骤&#10;填写可供实现类套用的模板" onChange={event => change('template', event.target.value)} />{fieldError('template')}</label>
      {message && <p className="error-banner" role="alert">{message}</p>}
      {catalog.error && <p className="error-banner" role="alert">{catalog.error}<button type="button" className="button small" onClick={() => void catalog.refresh().catch(() => {})}>重新加载阶段</button></p>}
    </form>
  </Dialog>
}
