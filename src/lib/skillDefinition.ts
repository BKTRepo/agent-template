import { applicationText } from '@/lib/access'
import type { Implementation } from '@/types/developer'

// 真实构建只显示指定 build_id 的快照，禁止用后来编辑的草稿覆盖。
export function skillDefinition(item: Implementation): [string, string][] | null {
  if (item.buildOrigin === 'backend') {
    const build = item.build
    if (!build || build.build_id !== item.buildId) return null
    const source = build.source
    return [
      ['技能名称', source.display_name ?? '未记录'], ['描述', source.description ?? '未记录'],
      ['版本号', build.version], ['执行指令', source.instructions ?? '未记录'],
      ['挂载知识库', source.knowledge_base_ids?.join('、') || '无'],
      ['资源文件', build.files.filter(row => row.path !== 'SKILL.md').map(row => row.path).join('、') || '无'],
      ['资源使用说明', source.resource_usage || '未设置'], ['运行环境要求', source.compatibility || '未设置'],
    ]
  }
  return [
    ['所属应用', applicationText(item)], ['技能名称', item.name], ['描述', item.description], ['版本号', item.version], ['执行指令', item.instructions],
    ['挂载知识库', item.knowledgeBases?.map(row => row.name).join('、') || item.resourceIds.join('、') || '无'],
    ['资源文件', item.uploadedResources?.map(row => row.name).join('、') || '无'],
    ['资源使用说明', item.resourceUsage || '未设置'], ['运行环境要求', item.compatibility || '未设置'],
  ]
}
