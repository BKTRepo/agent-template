import type { Implementation, KnowledgeBase } from '@/types/developer'

// 定稿 MVP 使用个人权限。应用使用全量只读目录，不按团队裁剪。
export const applications = ['信用卡系统', '核心系统', 'ATPM', 'FNP', 'BLIM', '测试平台', '平台官方'].map(name => ({ id: name, name }))
export const ALL_APPLICATIONS = '*'
export interface Actor { id: string; name: string }
export const demoActors: Actor[] = [
  { id: 'he', name: '何安涵' }, { id: 'li', name: '李明' },
  { id: 'wang', name: '王宁' }, { id: 'zhang', name: '张工' }, { id: 'zhou', name: '周工' },
]
export const actorApplications = (_actor: Actor) => applications
export function applicationText(item: { applicationIds?: string[]; system?: string }) {
  const ids = item.applicationIds ?? (item.system ? [item.system] : [])
  return ids.includes(ALL_APPLICATIONS) ? '全应用适用' : ids.join('、') || '未关联应用'
}
export function assertApplications(ids: string[] | undefined, _actor?: Actor) {
  if (!ids?.length) return
  if (new Set(ids).size !== ids.length || (ids.includes(ALL_APPLICATIONS) && ids.length !== 1)) throw new Error('全应用适用不能与具体应用同时选择。')
  if (ids.some(id => id !== ALL_APPLICATIONS && !applications.some(app => app.id === id))) throw new Error('只能选择应用目录中已有的应用。')
}
export const canEditImplementation = (item: Pick<Implementation, 'creatorId'>, actor: Actor) => !!item.creatorId && item.creatorId === actor.id
export function assertImplementationOwner(item: Pick<Implementation, 'creatorId'>, actor: Actor) {
  if (!canEditImplementation(item, actor)) throw new Error('只有创建者本人可以修改此实现类。')
}
export const canEditKnowledge = (item: Pick<KnowledgeBase, 'creatorId'>, actor: Actor) => !!item.creatorId && item.creatorId === actor.id
export const canViewKnowledge = (item: Pick<KnowledgeBase, 'creatorId' | 'scope'>, actor: Actor) => item.scope === 'public' || canEditKnowledge(item, actor)
