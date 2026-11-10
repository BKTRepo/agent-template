import { request } from './developerCenter'
import type { ImplementationForm } from '@/types/developer'

export const polishFields = {
  description: '描述',
  instructions: '执行指令',
  resourceUsage: '资源使用说明',
  compatibility: '运行环境要求',
}
export type SkillPolishText = Record<keyof typeof polishFields, string>
export const polishKeys = Object.keys(polishFields) as (keyof SkillPolishText)[]

export function polishText(form: ImplementationForm): SkillPolishText {
  return { description: form.description, instructions: form.instructions,
    resourceUsage: form.resourceUsage ?? '', compatibility: form.compatibility ?? '' }
}

export async function requestSkillPolish(original: SkillPolishText, signal: AbortSignal): Promise<SkillPolishText> {
  const result = await request<{ description: string; instructions: string; resource_usage: string; compatibility: string }>(
    '/skills/developer/polish-form', { method: 'POST', signal, body: JSON.stringify({
      description: original.description, instructions: original.instructions,
      resource_usage: original.resourceUsage, compatibility: original.compatibility,
    }) })
  return { description: result.description, instructions: result.instructions,
    resourceUsage: result.resource_usage, compatibility: result.compatibility }
}
