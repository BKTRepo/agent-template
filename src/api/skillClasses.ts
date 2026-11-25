import { request } from './developerCenter'
import type { SkillClassDetail, SkillClassForm, SkillClassOption, SkillClassPage, TestStage } from '@/types/skillClass'

const detail = (value: SkillClassDetail): SkillClassDetail => ({ ...value, id: String(value.id) })
export async function getSkillClassMetadata() {
  const data = await request<{ test_stages: TestStage[]; skill_classes: SkillClassOption[] }>('/skills/classes/get-metadata')
  return { test_stages: data.test_stages.map(row => ({ ...row, id: String(row.id) })),
    skill_classes: data.skill_classes.map(row => ({ ...row, id: String(row.id) })) }
}
export async function listSkillClasses(stageId = '', page = 1, signal?: AbortSignal): Promise<SkillClassPage> {
  const query = new URLSearchParams({ page: String(page), page_size: '10' })
  if (stageId) query.set('test_stage_id', stageId)
  const data = await request<SkillClassPage>(`/skills/classes/list?${query}`, { signal })
  return { ...data, items: data.items.map(detail), summary: { ...data.summary,
    stages: data.summary.stages.map(row => ({ ...row, id: String(row.id) })) } }
}
export async function getSkillClass(id: string, signal?: AbortSignal) {
  return detail(await request<SkillClassDetail>(`/skills/classes/get?${new URLSearchParams({ class_id: id })}`, { signal }))
}
export async function saveSkillClass(form: SkillClassForm, existing?: SkillClassDetail) {
  return detail(await request<SkillClassDetail>(`/skills/classes/${existing ? 'update' : 'create'}`, {
    method: 'POST', body: JSON.stringify({ ...form,
      ...(existing ? { class_id: Number(existing.id), expected_revision: existing.revision } : {}) }),
  }))
}
export function removeSkillClass(row: SkillClassDetail) {
  return request<{ removed: boolean; class_id: number; name: string }>('/skills/classes/remove', {
    method: 'POST', body: JSON.stringify({ class_id: Number(row.id), expected_revision: row.revision }),
  })
}

export async function publishSkillClass(row: SkillClassDetail) {
  return detail(await request<SkillClassDetail>('/skills/classes/publish', {
    method: 'POST', body: JSON.stringify({ class_id: Number(row.id), expected_revision: row.revision }),
  }))
}
