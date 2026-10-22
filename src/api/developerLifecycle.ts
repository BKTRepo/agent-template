import { validateSkillForm } from '@/lib/skillForm'
import type { PublishReply, Implementation, ImplementationForm } from '@/types/developer'
import { assertReadyToPublish } from '@/lib/publishing'
import { assertApplications, assertImplementationOwner } from '@/lib/access'
import { useAccessStore } from '@/stores/accessStore'
import { assertKnowledgeMounts } from '@/stores/knowledgeStore'
import { nextVersion } from '@/lib/version'
import { copySkillForm, withSystemVersion } from '@/lib/skillModel'
import { buildMockArchive, restoreSkillUploads } from '@/api/skillArchive'
import type { SkillUploads } from '@/types/developer'

// 这里只提供本地演示适配器。真实记录必须接对应保存/下线接口后才可改变。
function requireDemoOnline(item: Implementation) {
  assertImplementationOwner(item, useAccessStore.getState().actor)
  if (item.status !== '已上线') throw new Error('该技能当前不是已上线状态，请刷新后重试。')
  if (item.buildOrigin === 'backend' || item.backendSkillId) throw new Error('真实技能的保存修改、下线接口尚未接入，本次未修改服务器或本地状态。')
}

export async function saveOnlineChanges(item: Implementation, form: ImplementationForm, existing: Implementation[], uploads?: SkillUploads): Promise<Partial<Implementation>> {
  requireDemoOnline(item)
  assertApplications(form.applicationIds, useAccessStore.getState().actor)
  assertKnowledgeMounts(form.resourceIds)
  const issues = validateSkillForm(form, existing, item.id)
  if (Object.keys(issues).length) throw new Error(Object.values(issues)[0])
  // 只复制表单字段；不能把回显对象中的状态、旧上线/调试结果写入编辑稿。
  const pendingChanges: ImplementationForm = {
    classId: form.classId, name: form.name.trim(), technicalName: form.technicalName,
    system: form.system, team: form.team, version: form.version, modelTier: form.modelTier,
    applicationIds: [...(form.applicationIds ?? [])],
    description: form.description, instructions: form.instructions,
    compatibility: form.compatibility ?? '', resourceUsage: form.resourceUsage ?? '',
    resourceIds: [...form.resourceIds], knowledgeBases: form.knowledgeBases?.map(row => ({ ...row })) ?? [],
    uploadedResources: form.uploadedResources?.map(row => ({ ...row })) ?? [],
  }
  const updated = copySkillForm({ ...pendingChanges, skillMarkdown: form.skillMarkdown }, nextVersion(item.version))
  if (updated.skillMarkdown) updated.skillMarkdown = withSystemVersion(updated.skillMarkdown, updated.version)
  const build = await buildMockArchive({ ...item, ...updated }, await restoreSkillUploads(updated, uploads))
  // 已上线技能一旦保存内容修改，即回到草稿，必须使用新版本重新调试后才能再次上线。
  return { ...updated, ...build, status: '草稿', debug: undefined, pendingChanges: undefined, pendingChangedAt: undefined, publication: undefined }
}

export async function takeSkillOffline(item: Implementation): Promise<Partial<Implementation>> {
  requireDemoOnline(item)
  return { status: '已下线' }
}

export async function deleteDraft(item: Implementation): Promise<string> {
  assertImplementationOwner(item, useAccessStore.getState().actor)
  if (item.status !== '草稿') throw new Error('只有草稿可以删除。')
  if (item.backendSkillId || item.buildOrigin === 'backend') throw new Error('真实草稿的删除接口尚未接入，本次未删除服务器或本地记录。')
  return item.id
}

export async function publishSkill(item: Implementation): Promise<PublishReply> {
  const actor = useAccessStore.getState().actor
  assertImplementationOwner(item, actor)
  assertReadyToPublish(item)
  if (item.buildOrigin === 'backend' || item.backendSkillId) throw new Error('真实上线接口尚未接入，本次未修改服务器或本地发布状态。')
  await new Promise(resolve => setTimeout(resolve, 450))
  return {
    implementationId: item.id, buildId: item.buildId!, debugId: item.debug!.id,
    publication: { origin: 'mock', buildId: item.buildId!, publishedAt: new Date().toISOString(), publisher: actor.name },
  }
}
