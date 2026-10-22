import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Check, LoaderCircle, Plus } from 'lucide-react'
import Dialog from '@/components/developer/Dialog'
import DebugDialog from '@/components/developer/DebugDialog'
import SkillFields from '@/components/developer/SkillFields'
import { buildMockArchive, restoreSkillUploads } from '@/api/skillArchive'
import { applicationText, canEditImplementation, canViewKnowledge } from '@/lib/access'
import { useAccessStore } from '@/stores/accessStore'
import { useKnowledgeStore } from '@/stores/knowledgeStore'
import { skillResourceExtensions, validateResourceFiles, validateSkillForm } from '@/lib/skillForm'
import { checkSkillName, ensureSkill, readSkillDefinition, SkillApiError } from '@/api/skillClient'
import { hasSkillSession, skillAccount, skillBackendEnabled } from '@/api/skillSession'
import { generateSkill } from '@/api/developer'
import { deleteDraft as deleteDraftRecord, publishSkill, saveOnlineChanges, takeSkillOffline } from '@/api/developerLifecycle'
import { resources, skillClasses } from '@/mocks/developerData'
import { useDeveloperStore } from '@/stores/developerStore'
import { readBlob, saveBlobs } from '@/lib/resourceStorage'
import type { Implementation, ImplementationForm, SkillUploads } from '@/types/developer'

const steps = ['新建技能', '自测调试', '上线']
const blankForm = (team: string): ImplementationForm => ({ classId: '', name: '', technicalName: `skill-${crypto.randomUUID()}`, system: '核心系统', team, version: '1.0.0', modelTier: 'standard', description: '', instructions: '', compatibility: '', resourceIds: [], applicationIds: [], resourceUsage: '', knowledgeBases: [], uploadedResources: [] })
const dateText = (value: string) => new Date(value).toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
const statusClass = (status: string) => ['已上线', '调试通过'].includes(status) ? 'green' : ['调试失败', '执行超时'].includes(status) ? 'red' : ['草稿', '已下线'].includes(status) ? 'neutral' : 'orange'
function Status({ status }: { status: string }) { return <span className={`status-tag ${statusClass(status)}`}>{status}</span> }

export default function DeveloperPage() {
  const { implementations, save, patch, applyPublication } = useDeveloperStore()
  const actor = useAccessStore(state => state.actor)
  const team = ''
  const [preview, setPreview] = useState<Partial<Implementation>>({})
  const [panel, setPanel] = useState<'form' | 'debug' | null>(null)
  const [uploads, setUploads] = useState<SkillUploads>({ references: [], scripts: [] })
  const [selectedId, setSelectedId] = useState<string>()
  const [form, setForm] = useState<ImplementationForm>(() => blankForm(team))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<'build' | 'debug' | 'read' | 'save' | 'offline' | 'delete' | null>(null)
  const [message, setMessage] = useState('')
  const [notice, setNotice] = useState('')
  const nameCheckSequence = useRef(0)
  const formRoot = useRef<HTMLDivElement>(null)
  const [offlinePrompt, setOfflinePrompt] = useState(false)
  const [draftDeletePrompt, setDraftDeletePrompt] = useState(false)
  const record = implementations.find(item => item.id === selectedId)
  const selected = record ? { ...record, ...preview } : undefined
  const readonly = !!selected && !canEditImplementation(selected, actor)
  const online = selected?.status === '已上线'
  const mine = implementations.filter(item => item.creatorId === actor.id)
  const pending = mine.filter(item => ['草稿', '已生成', '调试中'].includes(item.status)).length
  const activeUploads = [...uploads.references, ...uploads.scripts]
  const validationErrors = Object.entries(errors).filter(([, value]) => !!value)

  function focusField(key: string) {
    window.requestAnimationFrame(() => {
      const field = Array.from(formRoot.current?.querySelectorAll<HTMLElement>('[data-skill-field]') ?? []).find(row => row.dataset.skillField === key)
      if (!field) return
      const control = field.querySelector<HTMLElement>('[aria-invalid="true"]') || field.querySelector<HTMLElement>('input:not([type="file"]),textarea,select') || field
      control.scrollIntoView({ block: 'center', behavior: 'smooth' })
      control.focus({ preventScroll: true })
    })
  }
  function showFormErrors(issues: Record<string, string>) {
    setErrors(issues); setMessage('')
    const first = Object.keys(issues).find(key => !!issues[key])
    if (first) focusField(first)
    return !!first
  }

  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(''), 4000); return () => window.clearTimeout(timer) }, [notice])
  function update<K extends keyof ImplementationForm>(key: K, value: ImplementationForm[K]) {
    setForm(previous => ({ ...previous, [key]: value }))
    setErrors(previous => ({ ...previous, [key]: '', ...(key === 'resourceIds' || key === 'uploadedResources' ? { resourceUsage: '' } : {}) })); setMessage('')
  }
  function openForm(item?: Implementation) {
    nameCheckSequence.current++
    setUploads({ references: [], scripts: [] })
    setPreview({})
    const editable = item && canEditImplementation(item, actor) ? item.pendingChanges ?? item : item
    const sequence = nameCheckSequence.current
    if (editable?.uploadedResources?.length) void Promise.all(editable.uploadedResources.map(async row => {
      const blob = await readBlob(`resource:${row.id}`)
      return blob ? { id: row.id, file: new File([blob], row.name, { lastModified: row.lastModified }), usage: row.category ?? '' } : undefined
    })).then(rows => { if (sequence === nameCheckSequence.current) { const found = rows.filter((row): row is NonNullable<typeof row> => !!row); setUploads({ references: found.filter(row => row.usage !== '脚本'), scripts: found.filter(row => row.usage === '脚本') }) } }).catch(() => { /* 缺失文件由生成/保存时提示重新选择。 */ })
    const knowledgeBases = editable?.knowledgeBases ?? resources.filter(row => row.kind === 'knowledge' && editable?.resourceIds.includes(row.id)).map(row => ({ id: row.id, name: row.name, source: 'mock' as const }))
    setSelectedId(item?.id); setForm(editable ? { ...editable, applicationIds: editable.applicationIds ?? [editable.system], technicalName: editable.technicalName || `skill-${crypto.randomUUID()}`, version: editable.version ?? '', resourceIds: knowledgeBases.map(row => row.id), knowledgeBases, resourceUsage: editable.resourceUsage ?? '', uploadedResources: editable.uploadedResources ?? [] } : blankForm(team)); setErrors({}); setMessage(''); setOfflinePrompt(false); setDraftDeletePrompt(false); setPanel('form')
  }
  function addFiles(files: File[]) {
    // 已存草稿中的同名文件重新选择时恢复实际文件，不重复添加记录。
    const descriptors = form.uploadedResources ?? []
    const missing = descriptors.filter(row => !activeUploads.some(upload => upload.id === row.id))
    const restoring = files.filter(file => missing.some(row => row.name === file.name && row.size === file.size && row.lastModified === file.lastModified))
    // 重新选择的草稿资源也要过类型/大小校验，仅从已有清单中暂扣，避免重复计数。
    const result = validateResourceFiles(files, descriptors.filter(row => !restoring.some(file => row.name === file.name && row.size === file.size && row.lastModified === file.lastModified)), skillResourceExtensions)
    const additions = result.accepted.map(file => ({ id: restoring.includes(file) ? missing.find(row => row.name === file.name)!.id : crypto.randomUUID(), file, usage: '' }))
    setUploads(previous => ({ references: [...previous.references, ...additions.filter(row => !/\.(py|js|sh|bash|ps1)$/i.test(row.file.name))], scripts: [...previous.scripts, ...additions.filter(row => /\.(py|js|sh|bash|ps1)$/i.test(row.file.name))] }))
    update('uploadedResources', [...descriptors, ...additions.filter(row => !descriptors.some(saved => saved.id === row.id)).map(row => ({ id: row.id, name: row.file.name, size: row.file.size, lastModified: row.file.lastModified }))])
    setErrors(previous => ({ ...previous, uploadedResources: result.errors.join('；') }))
  }
  function removeFile(id: string) {
    setUploads(previous => ({ references: previous.references.filter(row => row.id !== id), scripts: previous.scripts.filter(row => row.id !== id) }))
    update('uploadedResources', form.uploadedResources?.filter(row => row.id !== id) ?? [])
  }
  function closePanel() { if (!busy) { nameCheckSequence.current++; setPanel(null); setMessage(''); setOfflinePrompt(false); setDraftDeletePrompt(false) } }
  async function checkName() {
    const sequence = ++nameCheckSequence.current
    const localError = validateSkillForm(form, implementations, selectedId, true).name ?? ''
    setErrors(previous => ({ ...previous, name: localError }))
    if (localError || !hasSkillSession() || !skillBackendEnabled) return
    try {
      const excludeId = selected && selected.backendAccount === skillAccount() ? selected.backendSkillId : undefined
      const result = await checkSkillName(form.name.trim(), excludeId)
      if (sequence === nameCheckSequence.current) setErrors(previous => ({ ...previous, name: result.available ? '' : '技能名称已存在，请使用其他名称' }))
    } catch (error) {
      if (sequence === nameCheckSequence.current) setMessage((error as Error).message)
    }
  }
  async function openDebug(item: Implementation) {
    setPreview({}); setSelectedId(item.id); setMessage('')
    if (item.buildOrigin !== 'backend') { setPanel('debug'); return }
    setBusy('read')
    try {
      const definition = await readSkillDefinition(item)
      if (definition.build.build_id !== item.buildId) throw new Error('后端技能已更新，请重新查询当前构建后再调试。')
      const details = { build: definition.build, skillMarkdown: definition.markdown, version: definition.version, backendVersion: definition.version }
      if (canEditImplementation(item, actor)) patch(item.id, details); else setPreview(details); setPanel('debug')
    } catch (error) { setMessage((error as Error).message); setPanel(null) }
    finally { setBusy(null) }
  }
  async function saveDraft() {
    const issues = validateSkillForm(form, implementations, selectedId, true)
    if (showFormErrors(issues)) return
    setBusy('save')
    try {
      const restored = await restoreSkillUploads(form, uploads)
      await saveBlobs([...restored.references, ...restored.scripts].map(row => ({ key: `resource:${row.id}`, blob: row.file })))
      if (useAccessStore.getState().actor.id !== actor.id) throw new Error('用户已切换，草稿未保存。')
      save(form, selectedId); setPanel(null); setNotice('技能已保存，版本由系统生成，附件已保存在本机浏览器。')
    } catch (error) { setMessage((error as Error).message) } finally { setBusy(null) }
  }
  async function savePublished() {
    if (!selected || busy) return
    const issues = validateSkillForm(form, implementations, selected.id)
    if (showFormErrors(issues)) return
    setBusy('save'); setMessage('')
    try {
      const changes = await saveOnlineChanges(selected, form, implementations, uploads)
      if (useDeveloperStore.getState().implementations.find(row => row.id === selected.id)?.updatedAt !== selected.updatedAt) throw new Error('技能已发生变化，请重新打开后保存。')
      patch(selected.id, changes); setPanel(null)
      setNotice('修改已保存，版本由系统自动递增（本地模拟）。')
    } catch (error) { setMessage((error as Error).message) } finally { setBusy(null) }
  }
  async function offline() {
    if (!selected || busy) return
    setBusy('offline'); setMessage('')
    try {
      const changes = await takeSkillOffline(selected)
      if (useDeveloperStore.getState().implementations.find(row => row.id === selected.id)?.updatedAt !== selected.updatedAt) throw new Error('技能已发生变化，请重新打开后保存。')
      patch(selected.id, changes); setPanel(null); setOfflinePrompt(false)
      setNotice('技能已下线（模拟），仅更新本地演示状态；真实对外停用由后端处理。')
    } catch (error) { setMessage((error as Error).message) } finally { setBusy(null) }
  }
  async function removeDraft() {
    if (!selected || selected.status !== '草稿' || busy) return
    setBusy('delete'); setMessage('')
    try {
      const id = await deleteDraftRecord(selected)
      useDeveloperStore.getState().remove(id)
      setPanel(null); setDraftDeletePrompt(false)
      setNotice('草稿已删除。')
    } catch (error) { setMessage((error as Error).message) } finally { setBusy(null) }
  }
  async function build() {
    const issues = validateSkillForm(form, implementations, selectedId)
    if (form.resourceIds.some(id => { const kb = useKnowledgeStore.getState().knowledgeBases.find(row => row.id === id); return kb && !canViewKnowledge(kb, actor) })) issues.resourceIds = '所选知识库已不在当前用户的可见范围，请重新选择。'

    if (showFormErrors(issues)) return
    setBusy('build'); setMessage('')
    try {
      const item = save(form, selectedId); setSelectedId(item.id)
      if (!skillBackendEnabled) {
        const next = patchForDebug(item, await buildMockArchive(item, await restoreSkillUploads(item, uploads)))
        setNotice('Skill 示例 ZIP 已生成，可以运行沙箱调试。'); await openDebug(next); return
      }
      if (!hasSkillSession()) throw new SkillApiError('本地后端尚未配置有效会话，请检查联调服务与认证配置。')
      if (item.knowledgeBases?.some(row => row.source === 'mock')) throw new SkillApiError('真实生成不能使用示例知识库，请重新选择真实知识库或改用资源上传。', { resourceIds: '请使用真实知识库，或取消示例挂载。' })
      const backendSkillId = await ensureSkill(item)
      const backendAccount = skillAccount()
      patch(item.id, { backendSkillId, backendAccount })
      const readyUploads = await restoreSkillUploads(item, uploads)
      const result = await generateSkill({ ...item, backendSkillId, backendAccount }, readyUploads)
      const next = patchForDebug(item, { ...result, backendSkillId, backendAccount })
      setNotice('技能定义已生成，可以运行调试。'); await openDebug(next)
    } catch (error) { if (error instanceof SkillApiError) showFormErrors(error.fields); setMessage((error as Error).message) } finally { setBusy(null) }
  }
  function patchForDebug(item: Implementation, changes: Partial<Implementation>) {
    const next: Implementation = { ...item, ...changes, status: '调试中', debug: undefined, publication: undefined }
    patch(item.id, next); return next
  }
  async function publish() {
    const item = useDeveloperStore.getState().implementations.find(row => row.id === selectedId)
    if (!item) throw new Error('该实现类不存在，请刷新后重试。')
    applyPublication(await publishSkill(item))
    setPanel(null); setNotice('自测通过，技能已上线（模拟）。')
  }
  const primaryBusy = <><LoaderCircle className="spin" size={16} />处理中…</>

  return <>
    <div className="page-heading"><div><h1>开发者中心</h1></div><button className="button primary" onClick={() => openForm()}><Plus size={17} />新建技能类</button></div>
    <div className="developer-flow" aria-label="技能开发流程">{steps.map((step, index) => <div className="flow-step" key={step}><span className={`flow-node ${index === 0 ? 'done' : index === 1 ? 'current' : ''}`}><span>{['①', '②', '③'][index]}</span> {step}</span>{index < steps.length - 1 && <ArrowRight size={20} aria-hidden="true" />}</div>)}</div>
    <section className="surface implementation-section" aria-labelledby="implementation-title">
      <div className="section-heading"><h2 id="implementation-title">我创建的技能</h2><span className="status-tag orange">{pending} 个待处理</span></div>
      <div className="implementation-table-wrap"><table className="implementation-table"><thead><tr>{['实现名称', '技能类', '所属应用', '版本', '状态', '更新时间', '操作'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead><tbody>
        {mine.map(item => <tr key={item.id}><td className="implementation-name">{item.name}{!canEditImplementation(item, actor) && <span className="status-tag neutral">其他创建者 · 只读</span>}{item.pendingChanges && <span className="status-tag orange">有编辑稿</span>}</td><td>{skillClasses.find(row => row.id === item.classId)?.name}</td><td>{applicationText(item)}</td><td>{item.version}</td><td><Status status={item.status} /></td><td>{dateText(item.updatedAt)}</td><td><button className="button small" disabled={!!busy} onClick={() => { if (item.status === '调试中') openDebug(item); else openForm(item) }}>{item.status === '调试中' ? '调试' : '详情'}</button></td></tr>)}
        {!mine.length && <tr><td colSpan={7} className="empty-table">暂无实现类，点击“新建技能类”开始创建。</td></tr>}
      </tbody></table></div>
    </section>
    <p className="demo-note">运行调试完成后可下载 Excel 测试结果。</p>
    {!panel && message && <p className="error-banner" role="alert">{message}</p>}

    {panel === 'form' && <Dialog key="form" wide title={selected ? <>{readonly ? '实现类详情' : '编辑实现类'} · {selected.name}</> : '新建技能类'} onClose={closePanel} busy={!!busy} footer={<>
      {!!validationErrors.length && <div className="form-validation-summary" role="alert"><b>还有 {validationErrors.length} 项需要补充或修正：</b>{validationErrors.map(([key, value]) => <button key={key} type="button" onClick={() => focusField(key)}>{value}</button>)}</div>}
      {message && <p className="form-submit-error" role="alert">{message}</p>}
      {draftDeletePrompt ? <><span className="delete-confirm" role="alert">确认删除草稿“{selected?.name}”？删除后不可恢复。</span><button className="button" disabled={!!busy} onClick={() => setDraftDeletePrompt(false)}>取消删除</button><button className="button danger" disabled={!!busy} onClick={removeDraft}>{busy === 'delete' ? primaryBusy : '确认删除'}</button></> : offlinePrompt ? <><span className="delete-confirm" role="alert">确认下线“{selected?.name}”？未保存的编辑内容不会提交。</span><button className="button" disabled={!!busy} onClick={() => setOfflinePrompt(false)}>取消下线</button><button className="button danger" disabled={!!busy} onClick={offline}>{busy === 'offline' ? primaryBusy : '确认下线'}</button></> : <>
        <button className="button" disabled={!!busy} onClick={closePanel}>取消</button>
        {readonly ? <button className="button primary" disabled={!!busy || !selected?.buildId} onClick={() => selected && openDebug(selected)}>在线调试</button> : online ? <>
          <button className="button" disabled={!!busy} onClick={savePublished}>{busy === 'save' ? primaryBusy : '保存修改'}</button>
          <button className="button danger" disabled={!!busy} onClick={() => { setMessage(''); setOfflinePrompt(true) }}>下线</button>
          <button className="button primary" disabled={!!busy} onClick={() => selected && openDebug(selected)}>在线调试</button>
        </> : <>
          {selected?.status === '草稿' && <button className="button danger" disabled={!!busy} onClick={() => { setMessage(''); setDraftDeletePrompt(true) }}>删除草稿</button>}
          <button className="button" disabled={!!busy} onClick={saveDraft}>{selected ? '保存修改' : '保存草稿'}</button><button className="button primary" disabled={!!busy} onClick={build}>{busy === 'build' ? primaryBusy : selected?.status === '已下线' ? '重新上线' : selected ? '在线调试' : '调试'}</button>
        </>}
      </>}
    </>}>
      {readonly && <p className="form-hint">创建者：{selected?.creatorName || '历史创建者'}。仅创建者本人可编辑此实现类。</p>}
      {online && !readonly && <p className="helper-text">保存修改后系统自动递增版本；当前操作为前端模拟。{selected?.pendingChangedAt && `编辑稿保存于 ${dateText(selected.pendingChangedAt)}。`}</p>}
      {selected?.status === '已下线' && <p className="helper-text">该技能已下线。可继续编辑，重新调试通过后重新上线。</p>}
      <div ref={formRoot}><SkillFields form={form} update={update} errors={errors} disabled={!!busy || readonly} editing={!!selected} activeIds={activeUploads.map(row => row.id)} onAdd={addFiles} onRemove={removeFile} /></div>
    </Dialog>}

    {panel === 'debug' && selected && <DebugDialog key={selected.id} item={selected} onClose={closePanel} onEdit={!readonly && selected.status !== '已上线' ? () => openForm(selected) : undefined} onPublish={!readonly && selected.status !== '已上线' ? publish : undefined} onSaveDefinition={!readonly ? markdown => useDeveloperStore.getState().saveDefinition(selected.id, markdown) : undefined} onResult={debug => { if (readonly) setPreview(previous => ({ ...previous, debug })); else patch(selected.id, { debug }) }} />}
    {notice && <div className="platform-toast" role="status"><Check size={18} /><span>{notice}</span></div>}
  </>
}
