import { useKnowledgeStore } from '@/stores/knowledgeStore'
import { useDeveloperStore } from '@/stores/developerStore'
import { useAccessStore } from '@/stores/accessStore'
import { canViewKnowledge, assertImplementationOwner } from '@/lib/access'
import { copySkillForm } from '@/lib/skillModel'
import { nextVersion } from '@/lib/version'
import { validateSkillForm } from '@/lib/skillForm'
import { buildMockArchive, restoreSkillUploads } from './skillArchive'
import type { Implementation } from '@/types/developer'

export async function mountKnowledge(kbId: string, ids: string[], usage: string) {
  const actor = useAccessStore.getState().actor
  const kb = useKnowledgeStore.getState().knowledgeBases.find(row => row.id === kbId)
  if (!kb || !canViewKnowledge(kb, actor)) throw new Error('知识库不存在或没有挂载权限。')
  if (!ids.length) throw new Error('请选择要挂载的本人技能。')
  if (!usage.trim()) throw new Error('请填写该知识库的资源使用说明。')
  const store = useDeveloperStore.getState()
  const pending: { before: Implementation; changes: Partial<Implementation> }[] = []
  for (const id of [...new Set(ids)]) {
    const item = store.implementations.find(row => row.id === id)
    if (!item) throw new Error('部分目标技能已不存在，请重新搜索。')
    assertImplementationOwner(item, actor)
    if (item.backendSkillId || item.buildOrigin === 'backend') throw new Error('真实技能挂载关系保存接口未提供，未修改任何目标技能。')
    if (item.resourceIds.includes(kbId)) continue
    const form = copySkillForm({ ...item, resourceIds: [...item.resourceIds, kbId], knowledgeBases: [...(item.knowledgeBases ?? []), { id: kb.id, name: kb.name, source: 'mock' }], resourceUsage: [item.resourceUsage?.trim(), usage.trim()].filter(Boolean).join('\n') }, nextVersion(item.version))
    const issues = validateSkillForm(form, store.implementations, id)
    if (Object.keys(issues).length) throw new Error(`${item.name}：${Object.values(issues)[0]}，请先编辑技能。`)
    const built = item.status === '已上线' ? await buildMockArchive({ ...item, ...form }, await restoreSkillUploads(form)) : { buildId: undefined, buildOrigin: undefined }
    pending.push({ before: item, changes: { ...form, ...built, debug: undefined, publication: undefined, pendingChanges: undefined, status: item.status === '已上线' ? '已上线' : item.status === '已下线' ? '已下线' : '草稿' } })
  }
  if (useAccessStore.getState().actor.id !== actor.id) throw new Error('用户已切换，挂载未保存。')
  const currentKb = useKnowledgeStore.getState().knowledgeBases.find(row => row.id === kbId)
  if (!currentKb || !canViewKnowledge(currentKb, actor)) throw new Error('知识库可见范围已变化，请重新操作。')
  for (const { before } of pending) {
    const current = useDeveloperStore.getState().implementations.find(row => row.id === before.id)
    if (current?.updatedAt !== before.updatedAt || current?.version !== before.version) throw new Error('目标技能已变化，挂载未保存，请重新操作。')
  }
  for (const { before, changes } of pending) store.patch(before.id, changes)
  return pending.length
}
