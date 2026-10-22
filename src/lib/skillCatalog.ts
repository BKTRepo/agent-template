import { initialImplementations } from '@/mocks/developerData'
import { initialKnowledgeBases } from '@/mocks/knowledgeData'
import type { Implementation } from '@/types/developer'

const example = (source: Implementation, ids: string[]): Implementation => ({ ...source, id: `catalog-${source.id}`, status: '已上线', buildId: undefined, buildOrigin: 'mock', resourceIds: ids, knowledgeBases: ids.map(id => ({ id, name: initialKnowledgeBases.find(row => row.id === id)!.name, source: 'mock' })), uploadedResources: [], resourceUsage: '生成用例前读取业务规则与测试规范，核对字段与边界条件。' })
const examples = [example(initialImplementations[0], ['kb-credit', 'kb-standard']), example(initialImplementations[1], ['kb-core', 'kb-standard'])]

// 全量已上线目录：不按用户、小队或所属应用做权限过滤。
export function skillCatalog(implementations: Implementation[], onlineOnly = false) {
  const online = implementations.filter(item => item.status === '已上线' || (!onlineOnly && item.status === '已下线')).map(item => {
    const sample = examples.find(row => row.id === `catalog-${item.id}`)
    // 旧示例没有完整 ZIP，使用明确的样例资源补齐；当前记录的应用等元数据优先。
    return sample && !item.buildOrigin ? { ...sample, ...item, resourceIds: sample.resourceIds, knowledgeBases: sample.knowledgeBases, buildId: undefined, buildOrigin: 'mock' as const, resourceUsage: sample.resourceUsage } : item
  })
  return online
}
