import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Check, ChevronLeft, ChevronRight, LoaderCircle, Plus, RefreshCw } from 'lucide-react'
import Dialog from '@/components/developer/Dialog'
import DebugDialog from '@/components/developer/DebugDialog'
import SkillFields from '@/components/developer/SkillFields'
import { restoreSkillUploads } from '@/api/skillArchive'
import { applicationText, canViewKnowledge } from '@/lib/access'
import { useAccessStore } from '@/stores/accessStore'
import { useKnowledgeStore } from '@/stores/knowledgeStore'
import { skillResourceExtensions, validateResourceFiles, validateSkillForm } from '@/lib/skillForm'
import { checkSkillName, ensureSkill, readSkillDefinition, saveSkillDefinition, SkillApiError } from '@/api/skillClient'
import { hasSkillSession, skillAccount, skillBackendEnabled } from '@/api/skillSession'
import { generateSkill } from '@/api/developer'
import { persistSkillResources, createDeveloperSkill, deleteDeveloperSkill, offlineDeveloperSkill, publishDeveloperSkill, updateDeveloperSkill } from '@/api/developerCenter'
import { useDeveloperStore } from '@/stores/developerStore'
import { readBlob, saveBlobs } from '@/lib/resourceStorage'
import type { Implementation, ImplementationForm, SkillUploads } from '@/types/developer'

const steps = ['新建技能', '自测调试', '上线']
const blankForm = (team: string): ImplementationForm => ({ classId: '', name: '', technicalName: `skill-${crypto.randomUUID()}`, system: '核心系统', team, version: '1.0.0', modelTier: 'standard', description: '', instructions: '', compatibility: '', resourceIds: [], applicationIds: [], resourceUsage: '', knowledgeBases: [], uploadedResources: [] })
const dateText = (value: string) => new Date(value).toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
const statusClass = (status: string) => ['已上线', '调试成功'].includes(status) ? 'green' : ['调试失败', '执行超时'].includes(status) ? 'red' : ['草稿', '已下线'].includes(status) ? 'neutral' : 'orange'
function Status({ status }: { status: string }) { return <span className={`status-tag ${statusClass(status)}`}>{status}</span> }

export default function DeveloperPage() {
  const { implementations, skillClasses, applications, load, replace, patch, remove, loading, page, pages, total } = useDeveloperStore()
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
  const [offlineReasonCode, setOfflineReasonCode] = useState('')
  const [offlineReasonText, setOfflineReasonText] = useState('')
  const [draftDeletePrompt, setDraftDeletePrompt] = useState(false)
  const record = implementations.find(item => item.id === selectedId)
  const selected = record ? { ...record, ...preview } : undefined
  // 列表接口已按当前登录人过滤，服务端负责最终的本人编辑权限校验。
  const readonly = false
  const online = selected?.status === '已上线'
  const mine = implementations
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
  useEffect(() => { void load().catch(error => setMessage((error as Error).message)) }, [load])
  function update<K extends keyof ImplementationForm>(key: K, value: ImplementationForm[K]) {
    setForm(previous => ({ ...previous, [key]: value }))
    setErrors(previous => ({ ...previous, [key]: '', ...(key === 'resourceIds' || key === 'uploadedResources' ? { resourceUsage: '' } : {}) })); setMessage('')
  }
  function openForm(item?: Implementation) {
    nameCheckSequence.current++
    setUploads({ references: [], scripts: [] })
    setPreview({})
    const editable = item?.pendingChanges ?? item
    const sequence = nameCheckSequence.current
    if (editable?.uploadedResources?.length) void restoreSkillUploads(editable).then(found => {
      if (sequence === nameCheckSequence.current) setUploads(found)
    }).catch(error => { if (sequence === nameCheckSequence.current) setMessage((error as Error).message) })
    const knowledgeBases = editable?.knowledgeBases ?? []
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
      const excludeId = selected?.backendSkillId
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
      const details = { revision: definition.build.current_revision, skillVersionId: definition.build.skill_version_id, build: definition.build, skillMarkdown: definition.markdown, version: definition.version, backendVersion: definition.version }
      patch(item.id, details); setPanel('debug')
    } catch (error) { setMessage((error as Error).message); setPanel(null) }
    finally { setBusy(null) }
  }
  async function saveDraft() {
    const issues = validateSkillForm(form, implementations, selectedId, true)
    if (showFormErrors(issues)) return
    setBusy('save')
    try {
      const ready = await persistSkillResources(form, uploads)
      setForm(ready)
      const saved = selectedId ? await updateDeveloperSkill(selectedId, ready) : await createDeveloperSkill(ready)
      replace(saved); setPanel(null); setNotice('草稿已保存到后端数据库。')
    } catch (error) { setMessage((error as Error).message) } finally { setBusy(null) }
  }
  async function savePublished() {
    if (!selected || busy) return
    const issues = validateSkillForm(form, implementations, selected.id)
    if (showFormErrors(issues)) return
    setBusy('save'); setMessage('')
    try {
      const saved = await updateDeveloperSkill(selected.id, await persistSkillResources(form, uploads))
      replace(saved); setPanel(null)
      setNotice('修改已保存为新草稿，需重新调试后再上线。')
    } catch (error) { setMessage((error as Error).message) } finally { setBusy(null) }
  }
  async function offline() {
    if (!selected || busy) return
    setBusy('offline'); setMessage('')
    try {
      const saved = await offlineDeveloperSkill(selected.id, offlineReasonCode, offlineReasonCode === 'OTHER' ? offlineReasonText : undefined)
      replace(saved); setPanel(null); setOfflinePrompt(false)
      setNotice('技能已下线。')
    } catch (error) { setMessage((error as Error).message) } finally { setBusy(null) }
  }
  async function removeDraft() {
    if (!selected || selected.status !== '草稿' || busy) return
    setBusy('delete'); setMessage('')
    try {
      await deleteDeveloperSkill(selected.id)
      remove(selected.id)
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
      const ready = await persistSkillResources(form, uploads)
      setForm(ready)
      const item = selectedId ? await updateDeveloperSkill(selectedId, ready) : await createDeveloperSkill(ready)
      replace(item); setSelectedId(item.id)
      // 新建后立即进入构建流程时，当前表单仍然是创建前的草稿对象。
      // 回填后端返回的修订号，后续重试保存/构建才能携带 expected_revision。
      setForm(previous => ({ ...previous, revision: item.revision, skillVersionId: item.skillVersionId, version: item.version }))
      if (!skillBackendEnabled) throw new SkillApiError('后端生成服务尚未启用，不能使用前端模拟生成。')
      if (!hasSkillSession()) throw new SkillApiError('本地后端尚未配置有效会话，请检查联调服务与认证配置。')
      if (item.knowledgeBases?.some(row => row.source === 'mock')) throw new SkillApiError('真实生成不能使用示例知识库，请重新选择真实知识库或改用资源上传。', { resourceIds: '请使用真实知识库，或取消示例挂载。' })
      const backendSkillId = item.id
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
    if (!item) throw new Error('该技能不存在，请刷新后重试。')
    const saved = await publishDeveloperSkill(item.id)
    replace(saved)
    setPanel(null); setNotice('技能已上线。')
  }
  function saveDebugResult(id: string, debug: Implementation['debug']) {
    const current = useDeveloperStore.getState().implementations.find(row => row.id === id)
    if (!current) return
    // 弹窗切换、关闭或任务执行期间保存新版时，旧任务回调不能覆盖新版本/其他技能。
    if (debug && (debug.isCurrentVersion === false || debug.buildId !== current.buildId
      || (debug.skillVersionId && debug.skillVersionId !== current.skillVersionId))) return
    const terminalStatus = debug?.status === 'passed' ? '调试成功'
      : debug?.status === 'failed' || debug?.status === 'timeout' ? '调试失败'
        : debug?.status === 'queued' || debug?.status === 'running' ? '调试中' : undefined
    const status = terminalStatus && !['已上线', '已下线'].includes(current.status) ? terminalStatus : undefined
    patch(id, { debug, ...(status ? { status: status as Implementation['status'] } : {}) })
  }
  async function saveDefinition(markdown: string) {
    if (!selected) return
    const built = await saveSkillDefinition(selected, markdown)
    await load()
    const current = useDeveloperStore.getState().implementations.find(row => row.id === selected.id)
    if (!current) throw new Error('技能已不存在，请刷新后重试。')
    const definition = await readSkillDefinition(current)
    patch(current.id, { build: definition.build, buildId: built.build_id, buildOrigin: 'backend',
      skillMarkdown: definition.markdown, revision: definition.build.current_revision,
      skillVersionId: definition.build.skill_version_id, backendVersion: definition.version, version: definition.version })
    setPreview({})
  }
  async function refreshList() {
    if (loading || busy) return
    setMessage('')
    try { await load(page); setNotice('技能列表已刷新。') }
    catch (error) { setMessage((error as Error).message) }
  }
  function goToPage(nextPage: number) {
    if (loading || nextPage < 1 || nextPage > pages || nextPage === page) return
    setMessage('')
    void load(nextPage).catch(error => setMessage((error as Error).message))
  }
  const pageNumbers = Array.from({ length: pages }, (_, index) => index + 1)
  const primaryBusy = <><LoaderCircle className="spin" size={16} />处理中…</>

  return <>
    <div className="developer-flow surface" aria-label="技能开发流程">{steps.map((step, index) => <div className="flow-step" key={step}><span className={`flow-node ${index === 0 ? 'done' : index === 1 ? 'current' : ''}`}><span>{['①', '②', '③'][index]}</span> {step}</span>{index < steps.length - 1 && <ArrowRight size={20} aria-hidden="true" />}</div>)}</div>
    <section className="surface implementation-section" aria-labelledby="implementation-title">
      <div className="section-heading"><h2 id="implementation-title">我创建的技能</h2><div className="section-actions"><button className="button" disabled={loading || !!busy} onClick={() => void refreshList()}><RefreshCw size={14} className={loading ? 'spin' : undefined} />刷新</button><button className="button primary" disabled={loading || !!busy} onClick={() => openForm()}><Plus size={16} />新建技能</button></div></div>
      <div className="implementation-table-wrap"><table className="implementation-table"><thead><tr>{['实现名称', '技能类', '所属应用', '版本', '状态', '更新时间', '操作'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead><tbody>
        {mine.map(item => <tr key={item.id}><td className="implementation-name">{item.name}{item.pendingChanges && <span className="status-tag orange">有编辑稿</span>}</td><td>{skillClasses.find(row => row.id === item.classId)?.name}</td><td>{applicationText(item)}</td><td>{item.version}</td><td><Status status={item.status} /></td><td>{dateText(item.updatedAt)}</td><td><button className="button small" disabled={!!busy || loading} onClick={() => { if (['调试中', '调试成功', '调试失败'].includes(item.status)) openDebug(item); else openForm(item) }}>{['调试中', '调试成功', '调试失败'].includes(item.status) ? '调试' : '详情'}</button></td></tr>)}
        {!mine.length && <tr><td colSpan={7} className="empty-table">暂无实现类，点击“新建技能”开始创建。</td></tr>}
      </tbody></table></div>
      <div className="developer-pagination" aria-label="技能列表分页"><span className="pagination-total">共 {total} 条</span><button className="button small" disabled={loading || page <= 1} onClick={() => goToPage(page - 1)}><ChevronLeft size={14} />上一页</button><div className="pagination-pages">{pageNumbers.map(number => <button key={number} className={`button small ${number === page ? 'primary' : ''}`} aria-current={number === page ? 'page' : undefined} disabled={loading} onClick={() => goToPage(number)}>{number}</button>)}</div><button className="button small" disabled={loading || page >= pages} onClick={() => goToPage(page + 1)}>下一页<ChevronRight size={14} /></button></div>
    </section>
    <p className="demo-note">运行调试完成后可下载结果文档。</p>
    {!panel && message && <p className="error-banner" role="alert">{message}</p>}

    {panel === 'form' && <Dialog key="form" wide title={selected ? <>{readonly ? '实现类详情' : '编辑实现类'} · {selected.name}</> : '新建技能类'} onClose={closePanel} busy={!!busy} footer={<>
      {!!validationErrors.length && <div className="form-validation-summary" role="alert"><b>还有 {validationErrors.length} 项需要补充或修正：</b>{validationErrors.map(([key, value]) => <button key={key} type="button" onClick={() => focusField(key)}>{value}</button>)}</div>}
      {message && <p className="form-submit-error" role="alert">{message}</p>}
        {draftDeletePrompt ? <><span className="delete-confirm" role="alert">确认删除草稿“{selected?.name}”？删除后不可恢复。</span><button className="button" disabled={!!busy} onClick={() => setDraftDeletePrompt(false)}>取消删除</button><button className="button danger" disabled={!!busy} onClick={removeDraft}>{busy === 'delete' ? primaryBusy : '确认删除'}</button></> : <>
        <button className="button" disabled={!!busy} onClick={closePanel}>取消</button>
        {readonly ? <button className="button primary" disabled={!!busy || !selected?.buildId} onClick={() => selected && openDebug(selected)}>在线调试</button> : online ? <>
          <button className="button primary" disabled={!!busy} onClick={savePublished}>{busy === 'save' ? primaryBusy : '保存修改'}</button>
          <button className="button danger" disabled={!!busy} onClick={() => { setMessage(''); setOfflineReasonCode(''); setOfflineReasonText(''); setOfflinePrompt(true) }}>下线</button>
        </> : <>
          {selected?.status === '草稿' && <button className="button danger" disabled={!!busy} onClick={() => { setMessage(''); setDraftDeletePrompt(true) }}>删除草稿</button>}
          <button className={selected ? 'button primary' : 'button'} disabled={!!busy} onClick={saveDraft}>{selected ? '保存修改' : '保存草稿'}</button>{selected?.status !== '已下线' && <button className="button primary" disabled={!!busy} onClick={build}>{busy === 'build' ? primaryBusy : selected ? '在线调试' : '调试'}</button>}
        </>}
      </>}
    </>}>
      {readonly && <p className="form-hint">创建者：{selected?.creatorName || '历史创建者'}。仅创建者本人可编辑此实现类。</p>}
      {online && !readonly && <p className="helper-text">保存修改后系统自动递增版本，并回到草稿状态重新调试。{selected?.pendingChangedAt && `编辑稿保存于 ${dateText(selected.pendingChangedAt)}。`}</p>}
      {selected?.status === '已下线' && <p className="helper-text">该技能已下线。可继续编辑，重新调试通过后重新上线。</p>}
      <div ref={formRoot}><SkillFields form={form} update={update} skillClasses={skillClasses} applications={applications} errors={errors} disabled={!!busy || readonly} editing={!!selected} activeIds={activeUploads.map(row => row.id)} onAdd={addFiles} onRemove={removeFile} /></div>
    </Dialog>}

    {offlinePrompt && selected && <Dialog title={<>确认下线 · {selected.name}</>} onClose={() => setOfflinePrompt(false)} busy={!!busy} footer={<><button className="button" disabled={!!busy} onClick={() => setOfflinePrompt(false)}>取消下线</button><button className="button danger" disabled={!!busy || !offlineReasonCode || (offlineReasonCode === 'OTHER' && !offlineReasonText.trim())} onClick={offline}>{busy === 'offline' ? primaryBusy : '确认下线'}</button></>}>
      <p className="delete-confirm" role="alert">下线技能立即从技能中心移除，对话台已加载入口变为不可用；影响历史调用与产出记录保留，重新验证通过后可再次上线。</p>
      <label className="form-field"><span>下线原因 <em>*</em></span><select aria-label="下线原因" value={offlineReasonCode} onChange={event => setOfflineReasonCode(event.target.value)}><option value="">请选择下线原因</option><option value="ABILITY_DEFECT">能力缺陷</option><option value="COMPLIANCE_RISK">合规风险</option><option value="STOP_MAINTENANCE">停止维护</option><option value="OTHER">其他</option></select></label>
      {offlineReasonCode === 'OTHER' && <input value={offlineReasonText} onChange={event => setOfflineReasonText(event.target.value)} placeholder="请输入下线原因" />}
    </Dialog>}

    {panel === 'debug' && selected && <DebugDialog key={selected.id} item={selected} onClose={closePanel} onEdit={!readonly && !['已上线', '已下线'].includes(selected.status) ? () => openForm(selected) : undefined} onPublish={!readonly && !['已上线', '已下线'].includes(selected.status) ? publish : undefined} onSaveDefinition={!readonly ? saveDefinition : undefined} onResult={debug => saveDebugResult(selected.id, debug)} />}
    {notice && <div className="platform-toast" role="status"><Check size={18} /><span>{notice}</span></div>}
  </>
}
