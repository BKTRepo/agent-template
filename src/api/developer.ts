import type { DebugInput, Implementation } from '@/types/developer'
import type { SkillUploads } from '@/types/developer'
import { buildSkill, SkillApiError } from '@/api/skillClient'
import { validateSkillForm } from '@/lib/skillForm'
import { saveBlobs } from '@/lib/resourceStorage'

// 生成使用真实后端；沙箱保留明确标记的模拟接口。
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
export function validateBuild(item: Implementation): Record<string, string> {
  return validateSkillForm(item, [])
}
export async function generateSkill(item: Implementation, uploads: SkillUploads) {
  const errors = validateBuild(item)
  if (Object.keys(errors).length) throw new SkillApiError(Object.values(errors)[0], errors)
  // 真实生成后还要向独立调试服务提交原文件；与草稿/示例构建使用同一文件存储。
  await saveBlobs([...uploads.references, ...uploads.scripts].map(row => ({ key: `resource:${row.id}`, blob: row.file })))
  const build = await buildSkill(item, uploads)
  return { revision: build.current_revision, skillVersionId: build.skill_version_id, buildId: build.build_id, buildOrigin: 'backend' as const, build, technicalName: build.name, version: build.version, backendVersion: build.version }
}
export function validateInput(_item: Implementation, input: DebugInput | string) {
  const valid = typeof input === 'string' ? !!input.trim() : !!(input.conversation.trim() || input.documents.length)
  if (!valid) throw new Error('请填写对话或上传需求文档，至少提供一项输入。')
}
export async function runSandbox(item: Implementation, input: DebugInput | string, timeout: number, scenario: string) {
  if (!item.buildId) throw new Error('请先生成 Skill。')
  validateInput(item, input)
  if (!Number.isFinite(timeout) || timeout < 1 || timeout > 300) throw new Error('超时须为 1–300 秒。')
  await delay(1000)
  const status = scenario === 'failed' ? 'failed' : scenario === 'timeout' ? 'timeout' : 'passed'
  const output = status === 'passed'
    ? `✓ 沙箱上下文已准备\n✓ 挂载资源：${item.resourceIds.length + (item.uploadedResources?.length ?? 0)} 项\n✓ 输入参数校验通过\n✓ Skill 执行完成（模拟）\n\n${JSON.stringify({ status: 'success', output: { summary: '已覆盖正向、异常和边界场景', items: [{ title: '正常转账', expected: '交易成功，账务一致' }, { title: '余额不足', expected: '拒绝交易，账务不变' }, { title: '重复请求', expected: '幂等处理，无重复扣款' }] } }, null, 2)}\n\n耗时：1.0s · 本次结果来自模拟服务`
    : status === 'timeout' ? `沙箱执行超时（模拟，配置上限 ${timeout}s），请调整配置后重试。` : '沙箱执行失败（模拟）：资源读取异常，请检查挂载配置后重试。'
  const id = crypto.randomUUID()
  const artifact = status === 'passed' ? { key: `debug:${id}`, name: `${item.name.replace(/[\\/<>:"|?*]/g, '_')}-调试结果.md`, count: 3 } : undefined
  if (artifact) await saveBlobs([{ key: artifact.key, blob: new Blob([`# ${item.name} · 调试结果（前端模拟）\n\n版本：${item.version}\n\n本次示例共 3 条，调试输出最多 10 条。\n\n| 场景 | 预期结果 |\n| --- | --- |\n| 正常转账 | 交易成功，账务一致 |\n| 余额不足 | 拒绝交易，账务不变 |\n| 重复请求 | 幂等处理，无重复扣款 |\n\n> 仅演示文件输出流程，未执行脚本或调用模型。\n`], { type: 'text/markdown;charset=utf-8' }) }])
  return { id, buildId: item.buildId, input, status: status as 'passed' | 'failed' | 'timeout', output, artifact }
}
