import type { SkillClassOption, SkillClassForm, SkillClassDetail } from '@/types/skillClass'

export function hasSkillClassChanges(form: SkillClassForm, original: SkillClassDetail): boolean {
  if (form.test_stage_id !== (original.test_stage_id || 0)) return true
  return (['name', 'description', 'input_description', 'output_description', 'template'] as const).some(key => {
    const normalize = (value: string) => {
      const text = (value || '').replace(/\r\n?/g, '\n')
      return key === 'template' ? text : text.trim()
    }
    return normalize(form[key]) !== normalize(original[key])
  })
}

export function classesForStage<T extends SkillClassOption>(classes: T[], stageId: string) {
  return classes.filter(row => !stageId || String(row.test_stage_id ?? '') === stageId)
}
export function classAfterStageChange(classes: SkillClassOption[], stageId: string, classId: string) {
  return classesForStage(classes, stageId).some(row => row.id === classId) ? classId : ''
}
export function validateSkillClass(form: SkillClassForm): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const [field, limit, label] of [['name',20,'大类名称'],['description',500,'功能说明'],['input_description',200,'输入描述'],['template',100000,'Skill 模板']] as const) {
    const value = form[field].trim()
    if (!value) errors[field] = `请填写${label}`
    else if (Array.from(value).length > limit) errors[field] = `${label}最多 ${limit} 字`
  }
  if (!form.test_stage_id) errors.test_stage_id = '请选择测试所属阶段'
  if (Array.from(form.output_description.trim()).length > 200) errors.output_description = '输出描述最多 200 字'
  return errors
}
