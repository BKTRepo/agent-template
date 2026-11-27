export interface TestStage { id: string; code: string; name: string; description: string }
export interface SkillClassOption {
  id: string; name: string; is_enabled?: boolean; description?: string
  test_stage_id?: number | null; test_stage_name?: string | null; test_stage_code?: string | null
}
export interface SkillClassForm {
  name: string; test_stage_id: number; description: string
  input_description: string; output_description: string; template: string
}
export interface SkillClassDetail extends Omit<SkillClassOption, 'description'>, Omit<SkillClassForm, 'test_stage_id'> {
  class_code: string; test_stage_id: number | null; revision: number
  changed?: boolean
  input_schema: Record<string, unknown> | null; output_schema: Record<string, unknown> | null
  publication_status: 'DRAFT' | 'PUBLISHED'; published_revision: number | null; published_at: string | null
  has_unpublished_changes: boolean; can_publish: boolean; can_create_implementation: boolean
  creator_login_name: string | null; maintainer_name: string; implementation_count: number
  dependent_skill_count?: number
  created_time: string | null; updated_time: string | null
  is_mine: boolean; can_edit: boolean; can_delete: boolean; delete_disabled_reason: string | null
}
export interface SkillClassPage {
  items: SkillClassDetail[]; total: number; page: number; pages: number; page_size: number
  summary: { total: number; covered_stages: number; unassigned: number; stages: (TestStage & { count: number })[] }
}
