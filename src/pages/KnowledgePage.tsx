import { useEffect, useState } from 'react'
import { ArrowRight, Plus } from 'lucide-react'
import Dialog from '@/components/developer/Dialog'
import ListPagination from '@/components/common/ListPagination'
import NameDescription from '@/components/common/NameDescription'
import ResourceUpload from '@/components/developer/ResourceUpload'
import ApplicationPicker from '@/components/developer/ApplicationPicker'
import SearchSelect from '@/components/developer/SearchSelect'
import { useDeveloperStore } from '@/stores/developerStore'
import { useAccessStore } from '@/stores/accessStore'
import { filterKnowledgeBases, useKnowledgeStore, type KnowledgeForm } from '@/stores/knowledgeStore'
import { applicationText, canEditKnowledge, canMountKnowledge, canViewKnowledge, canRetryKnowledge, hasKnowledgeFailure, setApplicationCatalog, type Actor } from '@/lib/access'
import KnowledgeMountDialog from '@/components/developer/KnowledgeMountDialog'
import KnowledgeFilePreview from '@/components/developer/KnowledgeFilePreview'
import KnowledgeHistory from '@/components/developer/KnowledgeHistory'
import { nextVersion } from '@/lib/version'
import { knowledgeExtensions, knowledgeFileLimits, validateResourceFiles } from '@/lib/skillForm'
import { downloadBlob } from '@/lib/resourceStorage'
import { downloadKnowledgeFile, getKnowledgeMetadata, type KnowledgeMetadata } from '@/api/knowledge'
import { knowledgeCreationErrors, knowledgeEditSnapshot, knowledgeFileSizeError } from '@/lib/knowledgeForm'
import type { KnowledgeBase } from '@/types/developer'

const emptyForm = (actor: Actor): KnowledgeForm => ({ name: '', version: '', description: '', tag: '', scope: 'public', team: '', applicationIds: [], vectorized: false, model: '', files: [], processingOutcome: 'success' })
const timeText = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
const stages: Record<string, string> = { queued: '排队', splitting: '预处理', parsing: '解析', terminology: '术语提取', analyzing: '摘要分析', chunking: '分块', embedding: '向量入库', complete: '已入库', failed: '失败' }
export default function KnowledgePage() {
  const actor = useAccessStore(state => state.actor)
  const implementations = useDeveloperStore(state => state.implementations)
  const { knowledgeBases, save, retry, retryingIds, load, page, pages, pageSize, total, search, filters: appliedFilters, loading, error: loadError } = useKnowledgeStore()
  const [query, setQuery] = useState(search)
  const [filterApplication, setFilterApplication] = useState(appliedFilters.application)
  const [filterMaintainer, setFilterMaintainer] = useState(appliedFilters.maintainer)
  const [form, setForm] = useState<KnowledgeForm | null>(null)
  const [editing, setEditing] = useState<string>()
  const [originalContent, setOriginalContent] = useState<string | null>(null)
  const [detailId, setDetailId] = useState<string>()
  const [historyId, setHistoryId] = useState<string>()
  const [mountId, setMountId] = useState<string>()
  const [preview, setPreview] = useState<{kb: KnowledgeBase; id: string}>()
  const [uploads, setUploads] = useState<{ id: string; file: File }[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const [retryFeedback, setRetryFeedback] = useState<{ text: string; error: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const [metadata, setMetadata] = useState<KnowledgeMetadata>({ applications: [], tags: [] })
  const [metadataLoading, setMetadataLoading] = useState(true)
  const [metadataError, setMetadataError] = useState('')
  const formOpen = !!form
  useEffect(() => {
    const controller = new AbortController()
    setMetadataLoading(true); setMetadataError('')
    void getKnowledgeMetadata(controller.signal).then(value => {
      if (controller.signal.aborted) return
      setApplicationCatalog(value.applications); setMetadata(value)
    }).catch(error => { if (!controller.signal.aborted) setMetadataError((error as Error).message) })
      .finally(() => { if (!controller.signal.aborted) setMetadataLoading(false) })
    return () => controller.abort()
  }, [actor.id, formOpen])
  const edited = knowledgeBases.find(row => row.id === editing)
  const readonly = !!edited && !canEditKnowledge(edited, actor)
  const detail = knowledgeBases.find(row => row.id === detailId && canViewKnowledge(row, actor))
  const history = knowledgeBases.find(row => row.id === historyId && canViewKnowledge(row, actor))
  const items = filterKnowledgeBases(knowledgeBases, '', actor)
  const pagingBusy = loading
  function goToPage(target: number) {
    if (!pagingBusy && target >= 1 && target <= pages && target !== page) { setMessage(''); void load(target) }
  }
  const editUnchanged = !!editing && (!form || originalContent === null || knowledgeEditSnapshot(form) === originalContent)
  function open(item?: KnowledgeBase) { setOriginalContent(item ? knowledgeEditSnapshot(item) : null); setForm(item ? { ...item, applicationIds: [...(item.applicationIds ?? [])], files: item.files.map(file => ({ ...file })), changeSummary: '', processingOutcome: 'success' } : emptyForm(actor)); setEditing(item?.id); setUploads([]); setErrors({}); setMessage('') }
  function update<K extends keyof KnowledgeForm>(key: K, value: KnowledgeForm[K]) { setForm(previous => previous ? { ...previous, [key]: value } : previous); setErrors(previous => ({ ...previous, [key]: '' })); setMessage('') }
  function addFiles(files: File[]) {
    if (!form) return
    const result = validateResourceFiles(files, form.files, knowledgeExtensions, knowledgeFileLimits)
    const next = result.accepted.map(file => ({ id: crypto.randomUUID(), file }))
    setUploads(previous => [...previous, ...next])
    update('files', [...form.files, ...next.map(row => ({ id: row.id, name: row.file.name, size: row.file.size, lastModified: row.file.lastModified }))])
    setErrors(previous => ({ ...previous, files: result.errors.join('；') }))
  }
  async function submit() {
    if (!form || readonly || busy || metadataLoading || metadataError || editUnchanged) return
    const issues: Record<string, string> = editing ? {} : knowledgeCreationErrors(form)
    if (!form.name.trim()) issues.name = '请填写知识库名称'
    if (!form.files.length) issues.files = '请至少上传一个知识库文件'
    const sizeError = knowledgeFileSizeError(form.files)
    if (sizeError) issues.files = sizeError
    if ((form.applicationIds?.length ?? 0) > 1) issues.applicationIds = '最多选择一个所属应用'
    if (knowledgeBases.some(row => row.id !== editing && row.name.trim().normalize('NFKC').toLowerCase() === form.name.trim().normalize('NFKC').toLowerCase())) issues.name = '知识库名称已存在'
    setErrors(issues); if (Object.keys(issues).length) return
    setBusy(true)
    const initiatingActor = actor.id
    try {
      if (useAccessStore.getState().actor.id !== initiatingActor) throw new Error('用户已切换，请重新打开知识库。')
      const result = await save(form, editing, uploads)
      if (!editing) setQuery('')
      setForm(null)
      setMessage(editing ? result.version === form.version ? `未检测到实际修改，版本保持 ${result.version}。` : '知识库修改已保存，新增文档正在处理。' : '知识库已创建，文档正在处理，全部入库完成后可挂载。')
    } catch (error) { setMessage((error as Error).message) } finally { setBusy(false) }
  }
  async function download(kb: KnowledgeBase, id: string) {
    const file = kb.files.find(row => row.id === id)
    if (!file || !canViewKnowledge(kb, useAccessStore.getState().actor)) return
    try {
      const blob = await downloadKnowledgeFile(kb.id, id)
      downloadBlob(blob, file.name)
    } catch (error) { setMessage((error as Error).message) }
  }
  const error = (key: string) => errors[key] && <span role="alert" className="platform-field-error">{errors[key]}</span>
  async function retryKnowledge(kb: KnowledgeBase) {
    if (retryingIds.includes(kb.id)) return
    setRetryFeedback(null)
    try { await retry(kb.id); setRetryFeedback({ text: '已提交文档重试，正在查询真实进度。', error: false }) }
    catch (error) { setRetryFeedback({ text: (error as Error).message, error: true }) }
  }
  function retryButton(kb: KnowledgeBase) {
    if (!hasKnowledgeFailure(kb)) return null
    const allowed = canRetryKnowledge(kb, actor), pending = retryingIds.includes(kb.id)
    return <span title={allowed ? '重新处理失败文档，不增加知识库版本' : '仅创建者可重试该知识库'}><button className="button small" disabled={!allowed || pending} onClick={() => void retryKnowledge(kb)}>{pending ? '重试中…' : '重试'}</button>{!allowed && <small className="helper-text">仅创建者可重试</small>}</span>
  }
  return <>
    <div className="developer-flow surface" aria-label="知识库使用流程">
      {['新建知识库', '向量化检索', '挂载使用'].map((step, index) => <div className="flow-step" key={step}><span className={`flow-node ${index === 0 ? 'done' : index === 1 ? 'current' : ''}`}><span>{['①', '②', '③'][index]}</span> {step}</span>{index < 2 && <ArrowRight size={20} aria-hidden="true" />}</div>)}
    </div>
    <section className="surface knowledge-management"><div className="section-heading"><h2>知识库（多文件成库 · 可向量化检索）</h2><button className="button" onClick={() => open()}><Plus size={16} />新建知识库</button></div>
      <form className="management-filters knowledge-list-filters" role="search" aria-label="知识库筛选" onSubmit={event => { event.preventDefault(); if (!loading && !busy) { setMessage(''); void load(1, query, { application: filterApplication, maintainer: filterMaintainer }) } }}>
        <input aria-label="知识库名称模糊搜索" placeholder="知识库名称模糊搜索" maxLength={128} value={query} onChange={event => setQuery(event.target.value)} />
        <SearchSelect label="筛选所属应用" placeholder="全部应用" value={filterApplication} options={metadata.applications} disabled={metadataLoading || !!metadataError} onChange={setFilterApplication} />
        <input aria-label="维护人" placeholder="维护人姓名或账号" maxLength={64} value={filterMaintainer} onChange={event => setFilterMaintainer(event.target.value)} />
        <button type="submit" className="button primary" disabled={loading || busy}>搜索</button>
        <button type="button" className="button" disabled={loading || busy} onClick={() => { setQuery(''); setFilterApplication(''); setFilterMaintainer(''); setMessage(''); void load(1, '', { application: '', maintainer: '' }) }}>重置</button>
      </form>
      <div className="implementation-table-wrap" aria-busy={loading}><table className="implementation-table knowledge-table"><thead><tr>{['知识库', '文件数', '版本', '可见范围', '所属应用', '引用次数', '维护人', '状态', '操作'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{items.map(kb => <tr key={kb.id}><td className="implementation-name"><NameDescription name={kb.name} description={kb.description}><span className="status-tag neutral">{kb.tagName || kb.tag}</span></NameDescription></td><td>{kb.files.length}</td><td>{kb.version}</td><td><span className="status-tag blue">{kb.scope === 'public' ? '全体可见' : '仅本人可见'}</span></td><td>{applicationText(kb)}</td><td>{kb.referenceCount ?? implementations.filter(item => item.resourceIds.includes(kb.id)).length}</td><td>{kb.maintainer}</td><td><span role="status" className={`status-tag ${kb.processingStatus === '知识处理失败' ? 'red' : kb.processingStatus === '知识处理完成' ? 'green' : 'orange'}`}>{kb.processingStatus}</span></td><td><div className="table-actions"><button className="button small" onClick={() => setDetailId(kb.id)}>查看</button><button className="button small" disabled={!canMountKnowledge(kb, actor)} title={canMountKnowledge(kb, actor) ? "挂载到技能" : "知识处理完成后才可挂载到技能"} onClick={() => setMountId(kb.id)}>挂载到技能</button>{canEditKnowledge(kb, actor) && <button className="button small" onClick={() => open(kb)}>编辑</button>}<button className="button small" onClick={() => setHistoryId(kb.id)}>编辑历史</button>{retryButton(kb)}</div></td></tr>)}{!items.length && <tr><td colSpan={9} className="empty-table">{loading ? '正在加载知识库…' : (search || appliedFilters.application || appliedFilters.maintainer) ? '未找到符合筛选条件的知识库，请调整条件或重置。' : '暂无知识库，请点击“新建知识库”创建。'}</td></tr>}</tbody></table></div>
      <ListPagination total={total} page={page} pages={pages} pageSize={pageSize} label="知识库列表分页" busy={pagingBusy} onPageChange={goToPage} />
    </section>
    {!form && message && <p className="form-hint" role="status">{message}</p>}
    {retryFeedback && <p className={retryFeedback.error ? 'error-banner' : 'form-hint'} role={retryFeedback.error ? 'alert' : 'status'}>{retryFeedback.text}</p>}
    {loading && <p role="status">正在加载知识库…</p>}
    {loadError && <p className="error-banner" role="alert">{loadError} <button className="button small" onClick={() => void load(pagingBusy ? 1 : page, query, { application: filterApplication, maintainer: filterMaintainer })}>重新加载</button></p>}
    {metadataError && !form && <p className="error-banner" role="alert">筛选应用目录加载失败：{metadataError}</p>}
    {form && <Dialog wide title={readonly ? '知识库详情' : editing ? '编辑知识库' : '新建知识库'} busy={busy} onClose={() => setForm(null)} footer={<><button className="button" disabled={busy} onClick={() => setForm(null)}>{readonly ? '关闭' : '取消'}</button>{!readonly && <button className="button primary knowledge-save-button" disabled={busy || metadataLoading || !!metadataError || editUnchanged} title={editUnchanged ? '修改知识库内容后可保存' : undefined} onClick={submit}>{busy ? '保存中…' : editing ? '保存修改' : '创建知识库'}</button>}</>}>
      <fieldset className="implementation-form skill-create-form" disabled={busy || readonly}>
        <label className="form-field"><span>知识库名称 <em>*</em></span><input value={form.name} maxLength={128} placeholder="如：核心交易业务知识库" aria-invalid={!!errors.name} onChange={event => update('name', event.target.value)} />{error('name')}</label>
        {editing && <div className="form-field"><span>版本号</span><p className="form-hint">当前 {form.version}；保存修改后系统自动递增为 {nextVersion(form.version, 'V')}，不可手填。</p></div>}
        {editing && <label className="form-field"><span>变更摘要</span><textarea value={form.changeSummary ?? ''} maxLength={1000} aria-invalid={!!errors.changeSummary} placeholder="简述本次修改的内容，如补充退款规则、修正字段口径" onChange={event => update('changeSummary', event.target.value)} />{error('changeSummary')}</label>}
        <label className="form-field"><span>知识库描述 {!editing && <em>*</em>}</span><textarea value={form.description} required={!editing} aria-invalid={!!errors.description} maxLength={500} placeholder="描述知识库的用途、覆盖范围与更新策略" onChange={event => update('description', event.target.value)} />{error('description')}</label>
        <label className="form-field"><span>知识库标签 {!editing && <em>*</em>}</span><select aria-label="知识库标签" required={!editing} aria-invalid={!!errors.tag} value={form.tag} disabled={busy || readonly || metadataLoading || !!metadataError} onChange={event => update('tag', event.target.value)}><option value="" disabled hidden>请选择标签{editing ? '（选填）' : ''}</option>{form.tag && !metadata.tags.some(row => row.code === form.tag) && <option value={form.tag} disabled>{form.tagName || form.tag}（已停用）</option>}{metadata.tags.map(row => <option key={row.code} value={row.code}>{row.name}</option>)}</select>{form.tag && !readonly && editing && <button type="button" className="button small" disabled={busy} onClick={() => update('tag', '')}>清除标签</button>}</label>{error('tag')}
        <ApplicationPicker value={form.applicationIds} options={metadata.applications} required={!editing} disabled={busy || readonly || metadataLoading || !!metadataError} onChange={ids => update('applicationIds', ids)} />{error('applicationIds')}
        {metadataLoading && <p role="status" className="helper-text">正在加载应用目录和标签配置…</p>}{metadataError && <p role="alert" className="platform-field-error">{metadataError}</p>}

        <div className="form-field"><span>可见范围 <em>*</em></span><label className="inline-choice"><input type="radio" name="kb-scope" checked={form.scope === 'public'} onChange={() => update('scope', 'public')} />公开（所有用户可见、可挂载）</label><label className="inline-choice"><input type="radio" name="kb-scope" checked={form.scope === 'team'} onChange={() => update('scope', 'team')} />仅本人可见和挂载</label></div>
        <ResourceUpload label="上传文件" required hint="点击或拖拽上传知识库文件" extensions={knowledgeExtensions} limits={knowledgeFileLimits} items={form.files} activeIds={form.files.map(row => row.id)} error={errors.files} disabled={busy || readonly} onAdd={addFiles} onRemove={id => { setUploads(previous => previous.filter(row => row.id !== id)); update('files', form.files.filter(row => row.id !== id)) }} />
      </fieldset><KnowledgeHistory item={edited} />{message && <p className="error-banner" role="alert">{message}</p>}
    </Dialog>}
    {detail && <Dialog wide title={`知识库详情 · ${detail.name}`} onClose={() => setDetailId(undefined)} footer={<>{retryButton(detail)}<button className="button" onClick={() => setDetailId(undefined)}>关闭</button></>}><dl className="constraint-details">{[['描述', detail.description], ['版本号', detail.version], ['所属应用', applicationText(detail)], ['维护人', detail.maintainer], ['状态', detail.processingStatus], ['可见范围', detail.scope === 'public' ? '全体可见' : '仅本人可见'], ['创建者', detail.creatorName]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '未设置'}</dd></div>)}</dl><KnowledgeHistory item={detail} /><h3>知识库文件</h3>{detail.files.map(file => <div className="resource-row" key={file.id}><span>{file.name}{file.conversionStatus && <small> · {stages[file.conversionStatus] || '处理中'}</small>}{file.errorMessage && <small className="platform-field-error">{file.errorMessage}</small>}</span><button className="button small" onClick={() => setPreview({kb: detail, id: file.id})}>预览</button><button className="button small" onClick={() => download(detail, file.id)}>下载文件</button></div>)}{!detail.files.length && <p className="helper-text">暂无文件</p>}{retryFeedback && <p className={retryFeedback.error ? "error-banner" : "form-hint"} role={retryFeedback.error ? "alert" : "status"}>{retryFeedback.text}</p>}{message && <p role="status">{message}</p>}</Dialog>}
    {mountId && knowledgeBases.find(row => row.id === mountId) && <KnowledgeMountDialog kb={knowledgeBases.find(row => row.id === mountId)!} onClose={() => setMountId(undefined)} /> }
    {preview && <KnowledgeFilePreview kb={preview.kb} fileId={preview.id} onClose={() => setPreview(undefined)} />}
    {history && <Dialog wide title={`编辑历史 · ${history.name}`} onClose={() => setHistoryId(undefined)} footer={<button className="button" onClick={() => setHistoryId(undefined)}>关闭</button>}><p className="helper-text">记录每次更新的变更摘要、版本与维护人。</p><div className="knowledge-history">{history.history?.map(entry => <article key={entry.id}><div><b>{entry.version}</b><span>{entry.maintainer} · {timeText(entry.updatedAt)}</span></div><p>{entry.summary}</p></article>)}{!history.history?.length && <p>暂无历史编辑历史，后续保存修改时开始记录。</p>}</div></Dialog>}
  </>
}
