import { useEffect, useRef, useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import Dialog from './Dialog'
import ResourceUpload from './ResourceUpload'
import DebugResult from './DebugResult'
import { validateInput } from '@/api/developer'
import { debugDocumentLimit, downloadRealtimeDocuments, realtimeDebugEnabled, restoreRealtimeDebug, resumeRealtimeDebug, runRealtimeDebug } from '@/api/realtimeDebug'
import type { DebugMonitorOptions } from '@/api/realtimeDebug'
import { debugDocumentLimits, documentExtensions, validateResourceFiles } from '@/lib/skillForm'
import { renderSkillMarkdown } from '@/api/skillArchive'
import { skillDefinition } from '@/lib/skillDefinition'
import { downloadBlob, readBlob } from '@/lib/resourceStorage'
import type { DebugInput, Implementation } from '@/types/developer'

export default function DebugDialog({ item, onClose, onEdit, onPublish, onSaveDefinition, onResult }: { item: Implementation; onClose: () => void; onEdit?: () => void; onPublish?: () => Promise<void>; onSaveDefinition?: (markdown: string) => Promise<void>; onResult: (debug: Implementation['debug']) => void | Promise<void> }) {
  const initial = item.debug?.input
  const [input, setInput] = useState<DebugInput>({ conversation: typeof initial === 'string' ? initial : initial?.conversation ?? '', documentText: '', documents: [] })
  const [files, setFiles] = useState<{ id: string; file: File }[]>([])
  const [busy, setBusy] = useState<'run' | 'restore' | 'publish' | 'definition' | 'document' | null>(null)
  const [result, setResult] = useState(item.debug)
  const [error, setError] = useState('')
  const [definitionNotice, setDefinitionNotice] = useState('')
  const [editor, setEditor] = useState<string | null>(null)
  const [original, setOriginal] = useState('')
  const [discard, setDiscard] = useState(false)
  const requestRef = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const resultHandler = useRef(onResult)
  resultHandler.current = onResult
  const resultRef = useRef<HTMLDivElement>(null)
  function progressFor(current: number) {
    return async (debug: NonNullable<Implementation['debug']>) => {
      if (current !== generation.current) return
      setResult(debug)
      await resultHandler.current(debug)
    }
  }
  useEffect(() => {
    const current = ++generation.current
    const controller = new AbortController()
    requestRef.current = controller
    setResult(item.debug)
    if (realtimeDebugEnabled && item.buildOrigin === 'backend') {
      setBusy('restore'); setError('')
      void restoreRealtimeDebug(item, controller.signal, { onProgress: progressFor(current) })
        .then(debug => { if (current === generation.current && !controller.signal.aborted && !debug) setResult(undefined) })
        .catch(error => { if (current === generation.current && !controller.signal.aborted) setError((error as Error).message) })
        .finally(() => { if (current === generation.current) setBusy(null) })
    }
    return () => { generation.current++; controller.abort(); requestRef.current?.abort() }
  }, [item.id, item.buildId, item.skillVersionId])
  useEffect(() => {
    if (result?.id && !busy) resultRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [result?.id, busy])
  const definition = skillDefinition(item)
  const markdown = item.buildOrigin === 'backend' ? item.skillMarkdown || definition?.map(([label,value]) => `## ${label}\n${value}`).join('\n\n') || '' : renderSkillMarkdown(item)
  const mounted = item.knowledgeBases ?? []
  const mountedResources = item.buildOrigin === 'backend' ? (item.build?.files ?? []).filter(row => row.path !== 'SKILL.md').map(row => ({ id: row.path, name: row.path })) : [...mounted, ...(item.uploadedResources ?? [])]
  function change(value: DebugInput) { setInput(value); setError(''); setResult(undefined); void onResult(undefined) }
  function addDocuments(selected: File[]) {
    const result = validateResourceFiles(selected, input.documents, documentExtensions, debugDocumentLimits)
    const accepted = realtimeDebugEnabled ? result.accepted.slice(0, Math.max(0, debugDocumentLimit - input.documents.length)) : result.accepted
    if (accepted.length !== result.accepted.length) result.errors.push(`调试接口最多上传 ${debugDocumentLimit} 份需求文档。`)
    const additions = accepted.map(file => ({ id: crypto.randomUUID(), file }))
    setFiles(previous => [...previous, ...additions])
    change({ ...input, documents: [...input.documents, ...additions.map(row => ({ id: row.id, name: row.file.name, size: row.file.size, lastModified: row.file.lastModified }))] })
    setError(result.errors.join('；'))
  }
  async function download(debug = result) {
    const artifacts = debug?.artifacts?.length ? debug.artifacts : debug?.artifact ? [debug.artifact] : []
    for (const artifact of artifacts) {
      const blob = await readBlob(artifact.key)
      if (!blob) throw new Error(`调试结果文件“${artifact.name}”已丢失，请重试下载。`)
      downloadBlob(blob, artifact.name)
    }
  }
  async function executeDebug(work: (signal: AbortSignal, options: DebugMonitorOptions) => Promise<Implementation['debug']>, autoDownload = false) {
    requestRef.current?.abort()
    const current = ++generation.current
    const controller = new AbortController()
    requestRef.current = controller
    setError(''); setBusy('run')
    try {
      const debug = await work(controller.signal, { onProgress: progressFor(current) })
      if (current === generation.current && !controller.signal.aborted && autoDownload && debug?.artifact) await download(debug)
    } catch (error) {
      if (current === generation.current && !controller.signal.aborted) setError((error as Error).message)
    } finally { if (current === generation.current) setBusy(null) }
  }
  async function run() {
    if (busy) return
    try {
      if (!definition) throw new Error('请先查询本次构建定义。')
      validateInput(item, input)
      if (!realtimeDebugEnabled) throw new Error('沙箱调试服务尚未配置，不能使用前端模拟结果。')
      await executeDebug((signal, options) => runRealtimeDebug(item, input, markdown, files, signal, options), true)
    } catch (error) { setError((error as Error).message) }
  }
  async function resume() {
    if (busy || !result?.runId) return
    await executeDebug((signal, options) => resumeRealtimeDebug(item, result, signal, options))
  }
  async function retryDocument() {
    if (!result?.runId || busy) return
    setBusy('document'); setError('')
    const controller = new AbortController()
    requestRef.current = controller
    const timer = window.setTimeout(() => controller.abort(), 60_000)
    try {
      const artifacts = await downloadRealtimeDocuments(result.runId, item.name, result.documents ?? [], controller.signal)
      if (controller.signal.aborted) return
      const debug = { ...result, artifacts, artifact: artifacts[0], documentError: undefined }
      setResult(debug); await onResult(debug)
      await download(debug)
    } catch (error) { setError(controller.signal.aborted ? '下载请求超时，请重试下载。' : (error as Error).message) }
    finally { window.clearTimeout(timer); requestRef.current = null; setBusy(null) }
  }
  async function publish() {
    setBusy('publish'); setError('')
    try { await onPublish?.() } catch (error) { setError((error as Error).message) } finally { setBusy(null) }
  }
  function closeEditor() { if (busy) return; if (editor !== original) setDiscard(true); else setEditor(null) }
  async function saveDefinition() {
    if (editor === null || !onSaveDefinition) return
    setBusy('definition'); setError('')
    try { await onSaveDefinition(editor); setEditor(null); setDiscard(false); setDefinitionNotice('Skill 定义已保存，版本已自动更新。下载 ZIP 或运行真实调试时会检查挂载资源原文件。') } catch (error) { setError((error as Error).message) } finally { setBusy(previous => previous === 'definition' ? null : previous) }
  }
  const running = result?.status === 'queued' || result?.status === 'running'
  const locked = !!busy || running
  return <><Dialog wide closeWhileBusy title={<>在线调试 · {item.name}<span className="status-tag orange">沙箱</span></>} busy={!!busy} onClose={onClose} footer={<>
    <button className="button" onClick={onClose}>关闭</button>
    {onPublish && <button className="button" disabled={locked || !definition || !['调试中', '调试成功', '已生成'].includes(item.status) || result?.status !== 'passed' || result.buildId !== item.buildId || !result.versionRegistered || !result.isCurrentVersion || !!result.registrationError || !!result.monitorError || (realtimeDebugEnabled && (result.origin !== 'backend' || !result.artifact))} onClick={publish}>{busy === 'publish' ? '上线中…' : '上线'}</button>}
    {onEdit && <button className="button" disabled={locked} onClick={onEdit}>修改</button>}
    <button className="button primary" disabled={locked || !definition} onClick={run}>{running || busy === 'run' || busy === 'restore' ? <><LoaderCircle size={16} className="spin" />{busy === 'restore' ? '查询中…' : result?.status === 'queued' ? '排队中…' : '运行中…'}</> : '运行调试'}</button>
  </>}>
    <section className="form-field"><div className="field-heading"><span>Skill 定义（Markdown · 只读预览）</span>{onSaveDefinition && <button className="button small" disabled={locked || !definition} onClick={() => { setEditor(markdown); setOriginal(markdown); setDiscard(false); setError('') }}>编辑</button>}</div><pre className="markdown-preview">{markdown || '未读取到本次构建定义，请关闭后重新查询。'}</pre></section>
    <div className="form-field"><span>运行环境</span><p className="sandbox-settings">沙箱 · 隔离环境 · 执行后生成结果文档</p></div>
    {definitionNotice && <p className="form-hint" role="status">{definitionNotice}</p>}
    <label className="form-field"><span>对话输入（自然语言描述调试诉求）</span><textarea disabled={locked} value={input.conversation} placeholder="例如：帮我生成转账场景的正向、异常、边界用例，覆盖幂等与权限边界" onChange={event => change({ ...input, conversation: event.target.value })} /></label>
    <ResourceUpload label="文档输入（上传文件）" hint="拖拽或点击上传需求文档" extensions={documentExtensions} limits={debugDocumentLimits} items={input.documents} activeIds={files.map(row => row.id)} disabled={locked} onAdd={addDocuments} onRemove={id => { setFiles(previous => previous.filter(row => row.id !== id)); change({ ...input, documents: input.documents.filter(row => row.id !== id) }) }} />
    <div className="form-field"><span>挂载资源（本次调试关联，只读确认）</span>{mountedResources.map(row => <div className="resource-row" key={row.id}><span>{row.name}</span><span className="status-tag blue">已挂载</span></div>)}{!mountedResources.length && <p className="helper-text">未挂载资源</p>}</div>
    <div ref={resultRef}><DebugResult result={result} running={running} downloading={busy === 'document'} onRetry={result?.runId ? retryDocument : undefined} onResume={!busy && result?.runId ? resume : undefined} /></div>
    <p className="helper-text">运行调试将提交 Skill 定义、对话输入与原始文件；完成后可下载结果文档。最多10份需求文档、20份挂载资源。</p>
    {error && editor === null && <p className="error-banner" role="alert">{error}{result?.runId && !busy && <button className="button small" onClick={resume}>继续查询</button>}</p>}
  </Dialog>{editor !== null && <Dialog wide title="编辑 Skill 定义（Markdown）" busy={!!busy} onClose={closeEditor} footer={discard ? <><span role="alert">存在未保存修改，确认放弃？</span><button className="button" onClick={() => setDiscard(false)}>继续编辑</button><button className="button danger" onClick={() => { setEditor(null); setDiscard(false) }}>放弃修改</button></> : <><button className="button" disabled={!!busy} onClick={closeEditor}>取消</button><button className="button primary" disabled={!!busy} onClick={saveDefinition}>{busy ? '保存中…' : '保存'}</button></>}><p className="helper-text">保存后同步至我创建的技能，系统递增版本并使旧调试结果失效。版本由系统管理。</p><textarea className="markdown-editor" aria-label="Markdown Skill 定义" maxLength={200000} value={editor} disabled={!!busy} onChange={event => setEditor(event.target.value)} spellCheck={false} />{error && <p className="error-banner" role="alert">{error}</p>}</Dialog>}</>
}
