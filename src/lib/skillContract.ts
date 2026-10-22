import { skillClasses } from '@/mocks/developerData'
import type { Implementation } from '@/types/developer'
export function skillContract(item: Pick<Implementation, 'id' | 'name' | 'classId' | 'description'>) {
  const kind = skillClasses.find(row => row.id === item.classId)
  return { id: item.id, name: item.name, description: item.description, input: kind?.inputSchema ?? '需求文档 / 接口契约 / 业务规则', output: kind?.outputSchema ?? (item.classId === 'SKILL-DATA-002' ? 'TestData[] · 字段 / 类型 / 样例 / 约束' : 'TestCase[] · title / precondition / steps / expected') }
}
