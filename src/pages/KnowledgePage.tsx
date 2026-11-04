import { useState } from 'react'
import { ArrowRight, Plus } from 'lucide-react'
import Dialog from '@/components/developer/Dialog'
import ResourceUpload from '@/components/developer/ResourceUpload'
import ApplicationPicker from '@/components/developer/ApplicationPicker'
import { useDeveloperStore } from '@/stores/developerStore'
import { useAccessStore } from '@/stores/accessStore'
import { filterKnowledgeBases, useKnowledgeStore, type KnowledgeForm } from '@/stores/knowledgeStore'
import { applicationText, canEditKnowledge, canMountKnowledge, canViewKnowledge, type Actor } from '@/lib/access'
import KnowledgeMountDialog from '@/components/developer/KnowledgeMountDialog'
import KnowledgeFilePreview from '@/components/developer/KnowledgeFilePreview'
import KnowledgeHistory from '@/components/developer/KnowledgeHistory'
import { nextVersion } from '@/lib/version'
import { knowledgeExtensions, knowledgeFileLimits, validateResourceFiles } from '@/lib/skillForm'
import { downloadBlob } from '@/lib/resourceStorage'
import { downloadKnowledgeFile } from '@/api/knowledge'
import type { KnowledgeBase } from '@/types/developer'

const emptyForm = (actor: Actor): KnowledgeForm => ({ name: '', version: '', description: '', tag: '通识类', scope: 'public', team: '', applicationIds: [], vectorized: false, model: '', files: [], processingOutcome: 'success' })
const timeText = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
const stages: Record<string, string> = { queued: '排队', splitting: '预处理', parsing: '解析', terminology: '术语提取', analyzing: '摘要分析', chunking: '分块', embedding: '向量入库', complete: '已入库', failed: '失败' }
const progressText = (kb: KnowledgeBase) => { const files = kb.files.filter(file => file.conversionJobId); return files.length ? `${files.filter(file => file.conversionStatus === 'complete').length}/${files.length} 已入库 · ${[...new Set(files.map(file => stages[file.conversionStatus || ''] || '处理中'))].join('、')}` : '' }
export default function KnowledgePage() {
  const actor = useAccessStore(state => state.actor)
  const implementations = useDeveloperStore(state => state.implementations)
  const { knowledgeBases, save, retry, loading, error: loadError } = useKnowledgeStore()
  const [query, setQuery] = useState('')
  const [form, setForm] = useState<KnowledgeForm | null>(null)
  const [editing, setEditing] = useState<string>()
  const [detailId, setDetailId] = useState<string>()
  const [historyId, setHistoryId] = useState<string>()
  const [mountId, setMountId] = useState<string>()
  const [preview, setPreview] = useState<{kb: KnowledgeBase; id: string}>()
  const [uploads, setUploads] = useState<{ id: string; file: File }[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const edited = knowledgeBases.find(row => row.id === editing)
  const readonly = !!edited && !canEditKnowledge(edited, actor)
  const detail = knowledgeBases.find(row => row.id === detailId && canViewKnowledge(row, actor))
  const history = knowledgeBases.find(row => row.id === historyId && canViewKnowledge(row, actor))
  const items = filterKnowledgeBases(knowledgeBases, query, actor)
  function open(item?: KnowledgeBase) { setForm(item ? { ...item, files: [...item.files], changeSummary: '', processingOutcome: 'success' } : emptyForm(actor)); setEditing(item?.id); setUploads([]); setErrors({}); setMessage('') }
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
    if (!form || readonly || busy) return
    const issues: Record<string, string> = {}
    if (!form.name.trim()) issues.name = '请填写知识库名称'
    if (!form.files.length) issues.files = '请至少上传一个知识库文件'
    if ((form.applicationIds?.length ?? 0) > 1) issues.applicationIds = '最多选择一个所属应用'
    if (knowledgeBases.some(row => row.id !== editing && row.name.trim().normalize('NFKC').toLowerCase() === form.name.trim().normalize('NFKC').toLowerCase())) issues.name = '知识库名称已存在'
    setErrors(issues); if (Object.keys(issues).length) return
    setBusy(true)
    const initiatingActor = actor.id
    try {
      if (useAccessStore.getState().actor.id !== initiatingActor) throw new Error('用户已切换，请重新打开知识库。')
      await save(form, editing, uploads); setForm(null); setMessage(editing ? '知识库修改已保存，新增文档正在处理。' : '知识库已创建，文档正在处理，全部入库完成后可挂载。')
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
  return <>
    <div className="developer-flow surface" aria-label="知识库使用流程">
      {['新建知识库', '向量化检索', '挂载使用'].map((step, index) => <div className="flow-step" key={step}><span className={`flow-node ${index === 0 ? 'done' : index === 1 ? 'current' : ''}`}><span>{['①', '②', '③'][index]}</span> {step}</span>{index < 2 && <ArrowRight size={20} aria-hidden="true" />}</div>)}
    </div>
    <section className="surface knowledge-management"><div className="section-heading"><h2>知识库（多文件成库 · 可向量化检索）</h2><button className="button" onClick={() => open()}><Plus size={16} />新建知识库</button></div><div className="knowledge-search form-field"><input aria-label="知识库名称模糊搜索" placeholder="知识库名称模糊搜索" value={query} onChange={event => setQuery(event.target.value)} /><button className="button" onClick={() => setQuery('')}>重置</button></div>
      <div className="implementation-table-wrap"><table className="implementation-table knowledge-table"><thead><tr>{['知识库', '描述', '文件数', '版本', '可见范围', '所属应用', '引用次数', '维护人', '状态', '操作'].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{items.map(kb => <tr key={kb.id}><td className="implementation-name">{kb.name}<span className="status-tag neutral">{kb.tag}</span></td><td className="knowledge-description">{kb.description || '暂无描述'}</td><td>{kb.files.length}</td><td>{kb.version}</td><td><span className="status-tag blue">{kb.scope === 'public' ? '全体可见' : '仅本人可见'}</span></td><td>{applicationText(kb)}</td><td>{kb.referenceCount ?? implementations.filter(item => item.resourceIds.includes(kb.id)).length}</td><td>{kb.maintainer}</td><td><span role="status" className={`status-tag ${kb.processingStatus === '知识处理失败' ? 'red' : kb.processingStatus === '知识处理完成' ? 'green' : 'orange'}`}>{kb.processingStatus}</span><small className="helper-text">{progressText(kb)}</small></td><td><div className="table-actions"><button className="button small" onClick={() => setDetailId(kb.id)}>查看</button><button className="button small" disabled={!canMountKnowledge(kb, actor)} title={canMountKnowledge(kb, actor) ? "挂载到技能" : "知识处理完成后才可挂载到技能"} onClick={() => setMountId(kb.id)}>挂载到技能</button>{canEditKnowledge(kb, actor) && <button className="button small" onClick={() => open(kb)}>编辑</button>}<button className="button small" onClick={() => setHistoryId(kb.id)}>编辑历史</button>{kb.processingStatus === '知识处理失败' && canEditKnowledge(kb, actor) && <button className="button small" onClick={() => { void retry(kb.id).then(() => setMessage('已提交文档重试，正在查询真实进度。')).catch(error => setMessage(error.message)) }}>重试</button>}</div></td></tr>)}{!items.length && <tr><td colSpan={10} className="empty-table">{query.trim() ? '未找到可见的匹配知识库，请更换关键词。' : '暂无知识库，请点击“新建知识库”创建。'}</td></tr>}</tbody></table></div>
    </section>
    {!form && message && <p className="form-hint" role="status">{message}</p>}
    {loading && <p role="status">正在加载知识库…</p>}
    {loadError && <p className="error-banner" role="alert">{loadError} <button className="button small" onClick={() => void useKnowledgeStore.getState().load()}>重新加载</button></p>}
    {form && <Dialog wide title={readonly ? '知识库详情' : editing ? '编辑知识库' : '新建知识库'} busy={busy} onClose={() => setForm(null)} footer={<><button className="button" disabled={busy} onClick={() => setForm(null)}>{readonly ? '关闭' : '取消'}</button>{!readonly && <button className="button primary" disabled={busy} onClick={submit}>{busy ? '保存中…' : editing ? '保存修改' : '创建知识库'}</button>}</>}>
      <fieldset className="implementation-form skill-create-form" disabled={busy || readonly}>
        <label className="form-field"><span>知识库名称 <em>*</em></span><input value={form.name} maxLength={128} placeholder="如：核心交易业务知识库" aria-invalid={!!errors.name} onChange={event => update('name', event.target.value)} />{error('name')}</label>
        {editing && <div className="form-field"><span>版本号</span><p className="form-hint">当前 {form.version}；保存修改后系统自动递增为 {nextVersion(form.version, 'V')}，不可手填。</p></div>}
        {editing && <label className="form-field"><span>变更摘要</span><textarea value={form.changeSummary ?? ''} maxLength={1000} aria-invalid={!!errors.changeSummary} placeholder="简述本次修改的内容，如补充退款规则、修正字段口径" onChange={event => update('changeSummary', event.target.value)} />{error('changeSummary')}</label>}
        <label className="form-field"><span>知识库描述</span><textarea value={form.description} maxLength={500} placeholder="描述知识库的用途、覆盖范围与更新策略" onChange={event => update('description', event.target.value)} />{error('description')}</label>
        <label className="form-field"><span>知识库标签</span><select value={form.tag} onChange={event => update('tag', event.target.value)}><option value="">请选择标签（选填）</option><option>通识类</option><option>自定义</option></select></label>
        <ApplicationPicker value={form.applicationIds} disabled={busy || readonly} onChange={ids => update('applicationIds', ids)} />{error('applicationIds')}

        <div className="form-field"><span>可见范围 <em>*</em></span><label className="inline-choice"><input type="radio" name="kb-scope" checked={form.scope === 'public'} onChange={() => update('scope', 'public')} />公开（所有用户可见、可挂载）</label><label className="inline-choice"><input type="radio" name="kb-scope" checked={form.scope === 'team'} onChange={() => update('scope', 'team')} />仅本人可见和挂载</label></div>
        <ResourceUpload label="上传文件" required hint="点击或拖拽上传知识库文件" extensions={knowledgeExtensions} limits={knowledgeFileLimits} items={form.files} activeIds={form.files.map(row => row.id)} error={errors.files} disabled={busy || readonly} onAdd={addFiles} onRemove={id => { setUploads(previous => previous.filter(row => row.id !== id)); update('files', form.files.filter(row => row.id !== id)) }} />
      </fieldset><KnowledgeHistory item={edited} />{message && <p className="error-banner" role="alert">{message}</p>}
    </Dialog>}
    {detail && <Dialog wide title={`知识库详情 · ${detail.name}`} onClose={() => setDetailId(undefined)} footer={<button className="button" onClick={() => setDetailId(undefined)}>关闭</button>}><dl className="constraint-details">{[['描述', detail.description], ['版本号', detail.version], ['所属应用', applicationText(detail)], ['维护人', detail.maintainer], ['状态', detail.processingStatus], ['可见范围', detail.scope === 'public' ? '全体可见' : '仅本人可见'], ['创建者', detail.creatorName]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '未设置'}</dd></div>)}</dl><KnowledgeHistory item={detail} /><h3>知识库文件</h3>{detail.files.map(file => <div className="resource-row" key={file.id}><span>{file.name}{file.conversionStatus && <small> · {stages[file.conversionStatus] || '处理中'}</small>}{file.errorMessage && <small className="platform-field-error">{file.errorMessage}</small>}</span><button className="button small" onClick={() => setPreview({kb: detail, id: file.id})}>预览</button><button className="button small" onClick={() => download(detail, file.id)}>下载文件</button></div>)}{!detail.files.length && <p className="helper-text">暂无文件</p>}{message && <p role="status">{message}</p>}</Dialog>}
    {mountId && knowledgeBases.find(row => row.id === mountId) && <KnowledgeMountDialog kb={knowledgeBases.find(row => row.id === mountId)!} onClose={() => setMountId(undefined)} /> }
    {preview && <KnowledgeFilePreview kb={preview.kb} fileId={preview.id} onClose={() => setPreview(undefined)} />}
    {history && <Dialog wide title={`编辑历史 · ${history.name}`} onClose={() => setHistoryId(undefined)} footer={<button className="button" onClick={() => setHistoryId(undefined)}>关闭</button>}><p className="helper-text">记录每次更新的变更摘要、版本与维护人。</p><div className="knowledge-history">{history.history?.map(entry => <article key={entry.id}><div><b>{entry.version}</b><span>{entry.maintainer} · {timeText(entry.updatedAt)}</span></div><p>{entry.summary}</p></article>)}{!history.history?.length && <p>暂无历史编辑历史，后续保存修改时开始记录。</p>}</div></Dialog>}
  </>
}
