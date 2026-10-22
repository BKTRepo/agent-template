import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { initialImplementations } from '@/mocks/developerData'
import type { PublishReply, Implementation, ImplementationForm } from '@/types/developer'
import { validateSkillForm } from '@/lib/skillForm'
import { assertReadyToPublish } from '@/lib/publishing'
import { assertApplications, assertImplementationOwner } from '@/lib/access'
import { useAccessStore } from './accessStore'
import { assertKnowledgeMounts } from './knowledgeStore'
import { nextVersion } from '@/lib/version'
import { copySkillForm, withSystemVersion, markdownBody } from '@/lib/skillModel'
import { readSkillDefinition, saveSkillDefinition } from '@/api/skillClient'

interface DeveloperState {
  team: string
  implementations: Implementation[]
  setTeam: (team: string) => void
  save: (form: ImplementationForm, id?: string) => Implementation
  patch: (id: string, changes: Partial<Implementation>) => void
  remove: (id: string) => void
  applyPublication: (reply: PublishReply) => void
  saveDefinition: (id: string, markdown: string) => Promise<void>
}

// 沿用原存储键升级版本，保留表单/资源/构建。旧等待记录重新自测，绝不自动上线。
export function migrateDeveloperState(persisted: unknown) {
  const state = persisted as { team?: string; implementations?: (Omit<Implementation, 'status'> & { status: string; approval?: unknown })[] } | null
  const records = (state?.implementations ?? initialImplementations) as (Omit<Implementation, 'status'> & { status: string; approval?: unknown })[]
  return {
    team: state?.team || '测试一组',
    implementations: records.map(record => {
      const item = { ...record }
      delete item.approval
      if (item.status === '待审批') {
        item.status = item.buildId ? '调试中' : '草稿'
        item.debug = undefined
      }
      if (item.status === '已生成') item.status = '调试中'
      if (item.classId === 'SKILL-API-003') item.classId = 'SKILL-POINT-005'
      return { ...item, creatorId: item.creatorId ?? 'he', creatorName: item.creatorName ?? '何安涵', applicationIds: item.applicationIds ?? (item.system ? [item.system] : []), pendingChanges: item.pendingChanges ? { ...item.pendingChanges, applicationIds: item.pendingChanges.applicationIds ?? (item.pendingChanges.system ? [item.pendingChanges.system] : []) } : undefined } as Implementation
    }),
  }
}
export const useDeveloperStore = create<DeveloperState>()(persist((set, get) => ({
  team: '测试一组',
  implementations: initialImplementations,
  setTeam: team => set({ team }),
  save: (form, id) => {
    const previous = get().implementations.find(item => item.id === id)
    if (id && !previous) throw new Error('该实现类不存在，请刷新后重试。')
    const actor = useAccessStore.getState().actor
    if (previous) assertImplementationOwner(previous, actor)
    assertApplications(form.applicationIds, actor)
    assertKnowledgeMounts(form.resourceIds, actor)
    const errors = validateSkillForm(form, get().implementations, id, true)
    if (Object.keys(errors).length) throw new Error(Object.values(errors)[0])
    // 只保存表单字段，防止编辑回显携带的旧构建、上线和调试结果被重新写入。
    const item: Implementation = {
      classId: form.classId, name: form.name.trim(), technicalName: form.technicalName,
      system: form.system, team: form.team, version: form.version, modelTier: form.modelTier,
      applicationIds: [...(form.applicationIds ?? [])], creatorId: previous?.creatorId ?? actor.id, creatorName: previous?.creatorName ?? actor.name,
      description: form.description, instructions: form.instructions, resourceIds: [...form.resourceIds],
      resourceUsage: form.resourceUsage ?? '', knowledgeBases: form.knowledgeBases?.map(item => ({ ...item })) ?? [],
      uploadedResources: form.uploadedResources?.map(item => ({ ...item })) ?? [],
      compatibility: form.compatibility ?? '', backendSkillId: previous?.backendSkillId, backendAccount: previous?.backendAccount, backendVersion: previous?.backendVersion,
      id: id ?? crypto.randomUUID(), status: previous?.status === '已下线' ? '已下线' : '草稿', updatedAt: new Date().toISOString(),
    }
    Object.assign(item, copySkillForm(form, previous ? nextVersion(previous.version) : '1.0.0'))
    if (item.skillMarkdown) item.skillMarkdown = withSystemVersion(item.skillMarkdown, item.version)
    if (previous?.status === '已上线') throw new Error('已上线技能请使用保存修改入口。')
    set(state => ({ implementations: previous ? state.implementations.map(row => row.id === id ? item : row) : [item, ...state.implementations] }))
    return item
  },
  saveDefinition: async (id, markdown) => {
    const item = get().implementations.find(row => row.id === id)
    if (!item) throw new Error('该技能不存在。')
    assertImplementationOwner(item, useAccessStore.getState().actor)
    if (!markdown.trim() || markdown.length > 200000) throw new Error('Skill 定义不能为空，且最多 200000 个字符。')
    if (item.buildOrigin === 'backend' || item.backendSkillId) {
      const built = await saveSkillDefinition(item, markdown)
      const definition = await readSkillDefinition({ ...item, buildOrigin: 'backend', buildId: built.build_id })
      const current = get().implementations.find(row => row.id === id)
      if (current?.updatedAt !== item.updatedAt || current?.buildId !== item.buildId) throw new Error('技能已发生变化，请重新查询后端定义。')
      assertImplementationOwner(current, useAccessStore.getState().actor)
      set(state => ({ implementations: state.implementations.map(row => row.id === id ? { ...row, build: definition.build, buildOrigin: 'backend', buildId: definition.build.build_id, version: definition.version, backendVersion: definition.version, skillMarkdown: definition.markdown, instructions: definition.build.source.instructions || markdownBody(markdown), debug: undefined, publication: undefined, pendingChanges: undefined, updatedAt: new Date().toISOString() } : row) }))
      return
    }
    const version = nextVersion(item.version)
    const body = markdownBody(markdown)
    if (!body) throw new Error('请填写 Skill 定义正文。')
    const updated = { ...item, ...copySkillForm({ ...item, instructions: body, skillMarkdown: markdown }, version), debug: undefined, publication: undefined }
    // 定义编辑只保存文本和修订号。附件在实际打包/运行时检查，历史附件缺失不阻止编辑。
    // 使用新构建标识隔离旧 ZIP 与旧调试结果；下载时按当前修订重新生成包。
    const built = { buildId: `definition-${crypto.randomUUID()}`, buildOrigin: 'mock' as const, build: undefined }
    const current = get().implementations.find(row => row.id === id)
    if (current?.updatedAt !== item.updatedAt || current?.buildId !== item.buildId) throw new Error('技能已发生变化，请重新打开定义编辑器。')
    assertImplementationOwner(current, useAccessStore.getState().actor)
    set(state => ({ implementations: state.implementations.map(row => row.id === id ? { ...updated, ...built, status: row.status === '已上线' ? '已上线' : '调试中', pendingChanges: undefined, updatedAt: new Date().toISOString() } : row) }))
  },
  patch: (id, changes) => {
    const item = get().implementations.find(row => row.id === id)
    if (!item) throw new Error('该实现类不存在。')
    assertImplementationOwner(item, useAccessStore.getState().actor)
    set(state => ({ implementations: state.implementations.map(row => row.id === id ? { ...row, ...changes, creatorId: item.creatorId, creatorName: item.creatorName, updatedAt: new Date().toISOString() } : row) }))
  },
  remove: id => {
    const item = get().implementations.find(row => row.id === id)
    if (!item || item.status !== '草稿') throw new Error('只有存在的草稿可以删除。')
    assertImplementationOwner(item, useAccessStore.getState().actor)
    if (item.backendSkillId || item.buildOrigin === 'backend') throw new Error('真实草稿删除需要接入后端接口。')
    set(state => ({ implementations: state.implementations.filter(item => item.id !== id) }))
  },
  applyPublication: reply => {
    const item = get().implementations.find(row => row.id === reply.implementationId)
    if (!item || !['调试中', '已生成'].includes(item.status) || item.buildId !== reply.buildId || item.debug?.id !== reply.debugId) throw new Error('上线响应已过期，未覆盖当前版本状态。')
    assertImplementationOwner(item, useAccessStore.getState().actor)
    assertReadyToPublish(item)
    if (reply.publication.origin === 'mock' && (item.backendSkillId || item.buildOrigin === 'backend')) throw new Error('模拟上线不能改变真实技能的发布状态。')
    if (reply.publication.buildId !== reply.buildId) throw new Error('上线响应与当前构建不匹配。')
    set(state => ({ implementations: state.implementations.map(row => row.id === item.id ? { ...row, status: '已上线', publication: { ...reply.publication }, updatedAt: new Date().toISOString() } : row) }))
  },
}), { name: 'znfwdd-developer-center-v1', version: 4, migrate: migrateDeveloperState }))
