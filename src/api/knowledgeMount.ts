import { useKnowledgeStore } from '@/stores/knowledgeStore'
import { useDeveloperStore } from '@/stores/developerStore'
import { useAccessStore } from '@/stores/accessStore'
import { useAuthStore } from '@/stores/authStore'
import { canMountKnowledge } from '@/lib/access'
import { getKnowledgeBase } from './knowledge'
import { listDeveloperSkillsPage, updateDeveloperSkill } from './developerCenter'
import type { Implementation } from '@/types/developer'

export async function loadOwnedMountTargets(): Promise<Implementation[]> {
  const actor = useAccessStore.getState().actor.id
  if (!actor) throw new Error('平台身份尚未加载。')
  const items: Implementation[] = []
  let page = 1, pages = 1
  do {
    const result = await listDeveloperSkillsPage(page, 10)
    if (useAccessStore.getState().actor.id !== actor) throw new Error('平台身份已切换，请重新打开挂载窗口。')
    items.push(...result.items); pages = result.pages; page++
  } while (page <= pages)
  return [...new Map(items.filter(item => item.creatorId === actor).map(item => [item.id, item])).values()]
}
export interface KnowledgeMountResult { matched: number; saved: number; skipped: number; failures: { id: string; name: string; message: string }[]; refreshWarning?: string }
export async function mountKnowledge(kbId: string, skillIds: string[]): Promise<KnowledgeMountResult> {
  const actor = useAccessStore.getState().actor
  const token = useAuthStore.getState().session?.token
  const current = () => useAccessStore.getState().actor.id === actor.id && useAuthStore.getState().session?.token === token
  const kb = await getKnowledgeBase(kbId)
  if (!canMountKnowledge(kb, actor)) throw new Error('知识库尚未入库完成或没有读取权限。')
  if (!skillIds.length) throw new Error('请至少选择一个技能实现。')
  const selected = new Set(skillIds.map(String))
  const targets = (await loadOwnedMountTargets()).filter(item => selected.has(item.id))
  if (targets.length !== selected.size) throw new Error('所选技能实现不存在或非本人创建，请刷新后重新选择。')
  const result: KnowledgeMountResult = { matched: targets.length, saved: 0, skipped: 0, failures: [] }
  for (const item of targets) {
    if (!current()) throw new Error('平台身份已切换，批量更新已停止；已保存的结果保留在服务端。')
    if (item.resourceIds.includes(kbId)) { result.skipped++; continue }
    try {
      // Delegate the entire save/version/binding operation to the canonical skill update API.
      const updated = await updateDeveloperSkill(item.backendSkillId || item.id, { ...item,
        resourceIds: [...item.resourceIds, kbId],
        knowledgeBases: [...(item.knowledgeBases || []).filter(row => row.id !== kbId), { id: kbId, name: kb.name, source: 'backend' }],
        resourceUsage: item.resourceUsage?.trim() || `执行时检索“${kb.name}”，用于核对相关业务规则。`,
      })
      if (!current()) throw new Error('平台身份已切换，请重新加载保存结果。')
      useDeveloperStore.getState().replace(updated); result.saved++
    } catch (error) { result.failures.push({ id: item.id, name: item.name, message: (error as Error).message }) }
  }
  if (current()) {
    try { const updated = await getKnowledgeBase(kbId); if (current()) useKnowledgeStore.getState().replace(updated) }
    catch (error) { result.refreshWarning = `挂载结果已保存，知识库列表刷新失败：${(error as Error).message}` }
  }
  return result
}
