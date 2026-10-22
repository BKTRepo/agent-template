import { useEffect, useRef, useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import Dialog from './Dialog'
import ResourceUpload from './ResourceUpload'
import DebugResult from './DebugResult'
import { runSandbox, validateInput } from '@/api/developer'
import { debugDocumentLimit, downloadRealtimeDocument, realtimeDebugEnabled, runRealtimeDebug } from '@/api/realtimeDebug'
import { debugDocumentLimits, documentExtensions, validateResourceFiles } from '@/lib/skillForm'
import { renderSkillMarkdown } from '@/api/skillArchive'
import { skillDefinition } from '@/lib/skillDefinition'
import { downloadBlob, readBlob } from '@/lib/resourceStorage'
import { resources } from '@/mocks/developerData'
import type { DebugInput, Implementation } from '@/types/developer'

export default function DebugDialog({ item, onClose, onEdit, onPublish, onSaveDefinition, onResult }: { item: Implementation; onClose: () => void; onEdit?: () => void; onPublish?: () => Promise<void>; onSaveDefinition?: (markdown: string) => Promise<void>; onResult: (debug: Implementation['debug']) => void }) {
  const initial = item.debug?.input
  const [input, setInput] = useState<DebugInput>({ conversation: typeof initial === 'string' ? initial : initial?.conversation ?? '', documentText: '', documents: [] })
  const [files, setFiles] = useState<{ id: string; file: File }[]>([])
  const [scenario, setScenario] = useState('passed')
  const [busy, setBusy] = useState<'run' | 'publish' | 'definition' | 'document' | null>(null)
  const [error, setError] = useState('')
  const [definitionNotice, setDefinitionNotice] = useState('')
  const [editor, setEditor] = useState<string | null>(null)
  const [original, setOriginal] = useState('')
  const [discard, setDiscard] = useState(false)
  const requestRef = useRef<AbortController | null>(null)
  const resultRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (item.debug?.id && !busy) resultRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [item.debug?.id, busy])
  const definition = skillDefinition(item)
  const markdown = item.buildOrigin === 'backend' ? item.skillMarkdown || definition?.map(([label,value]) => `## ${label}\n${value}`).join('\n\n') || '' : renderSkillMarkdown(item)
  const mounted = item.knowledgeBases ?? resources.filter(row => item.resourceIds.includes(row.id)).map(row => ({ id: row.id, name: row.name }))
  const mountedResources = item.buildOrigin === 'backend' ? (item.build?.files ?? []).filter(row => row.path !== 'SKILL.md').map(row => ({ id: row.path, name: row.path })) : [...mounted, ...(item.uploadedResources ?? [])]
  function change(value: DebugInput) { setInput(value); setError(''); onResult(undefined) }
  function addDocuments(selected: File[]) {
    const result = validateResourceFiles(selected, input.documents, documentExtensions, debugDocumentLimits)
    const accepted = realtimeDebugEnabled ? result.accepted.slice(0, Math.max(0, debugDocumentLimit - input.documents.length)) : result.accepted
    if (accepted.length !== result.accepted.length) result.errors.push(`调试接口最多上传 ${debugDocumentLimit} 份需求文档。`)
    const additions = accepted.map(file => ({ id: crypto.randomUUID(), file }))
    setFiles(previous => [...previous, ...additions])
    change({ ...input, documents: [...input.documents, ...additions.map(row => ({ id: row.id, name: row.file.name, size: row.file.size, lastModified: row.file.lastModified }))] })
    setError(result.errors.join('；'))
  }
  async function download(result = item.debug) {
    if (!result?.artifact) return
    const blob = await readBlob(result.artifact.key)
    if (!blob) throw new Error('调试结果文件已丢失，请重新运行调试。')
    downloadBlob(blob, result.artifact.name)
  }
  async function run() {
    try {
      if (!definition) throw new Error('请先查询本次构建定义。')
      validateInput(item, input)
      setError(''); setBusy('run')
      // 先写入持久化状态。关闭弹窗不会中断请求，返回结果后仍会覆盖为成功或失败状态。
      onResult({ id: crypto.randomUUID(), buildId: item.buildId!, input, status: 'running', output: '正在运行调试，请稍候。', origin: realtimeDebugEnabled ? 'backend' : 'mock' })
      const result = realtimeDebugEnabled ? await runRealtimeDebug(item, input, markdown, files) : await runSandbox(item, input, 30, scenario)
      onResult(result)
      if (result.status === 'passed' && result.artifact) await download(result)
    } catch (error) { setError((error as Error).message) } finally { setBusy(null) }
  }
  async function retryDocument() {
    if (!item.debug?.runId || busy) return
    setBusy('document'); setError('')
    const controller = new AbortController()
    requestRef.current = controller
    const timer = window.setTimeout(() => controller.abort(), 60_000)
    try {
      const artifact = await downloadRealtimeDocument(item.debug.runId, item.name, controller.signal)
      if (controller.signal.aborted) return
      const result = { ...item.debug, artifact, documentError: undefined }
      onResult(result)
      await download(result)
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
    try { await onSaveDefinition(editor); setEditor(null); setDiscard(false); setDefinitionNotice('Skill 定义已保存，版本已自动更新。下载 ZIP 或运行真实调试时会检查挂载资源原文件。') } catch (error) { setError((error as Error).message) } finally { setBusy(null) }
  }
  const running = busy === 'run' || item.debug?.status === 'running'
  return <><Dialog wide closeWhileBusy title={<>在线调试 · {item.name}<span className="status-tag orange">沙箱</span></>} busy={!!busy} onClose={onClose} footer={<>
    <button className="button" onClick={onClose}>关闭</button>
    {onPublish && <button className="button" disabled={!!busy || !definition || !['调试中', '已生成'].includes(item.status) || item.debug?.status !== 'passed' || item.debug.buildId !== item.buildId || (realtimeDebugEnabled && (item.debug.origin !== 'backend' || !item.debug.artifact))} onClick={publish}>{busy === 'publish' ? '上线中…' : '上线'}</button>}
    {onEdit && <button className="button" disabled={!!busy} onClick={onEdit}>修改</button>}
    <button className="button primary" disabled={!!busy || running || !definition} onClick={run}>{running ? <><LoaderCircle size={16} className="spin" />运行中…</> : '运行调试'}</button>
  </>}>
    <section className="form-field"><div className="field-heading"><span>Skill 定义（Markdown · 只读预览）</span>{onSaveDefinition && <button className="button small" disabled={!!busy || !definition} onClick={() => { setEditor(markdown); setOriginal(markdown); setDiscard(false); setError('') }}>编辑</button>}</div><pre className="markdown-preview">{markdown || '未读取到本次构建定义，请关闭后重新查询。'}</pre></section>
    <div className="form-field"><span>运行环境</span><p className="sandbox-settings">{realtimeDebugEnabled ? '真实调试服务 · 执行后生成 Excel 测试用例文档' : '沙箱 · 隔离环境 · 仅模拟执行 · 不写入外部系统'}</p></div>
    {definitionNotice && <p className="form-hint" role="status">{definitionNotice}</p>}
    <label className="form-field"><span>对话输入（自然语言描述调试诉求）</span><textarea disabled={!!busy} value={input.conversation} placeholder="例如：帮我生成转账场景的正向、异常、边界用例，覆盖幂等与权限边界" onChange={event => change({ ...input, conversation: event.target.value })} /></label>
    <ResourceUpload label="文档输入（上传文件）" hint="拖拽或点击上传需求文档" extensions={documentExtensions} limits={debugDocumentLimits} items={input.documents} activeIds={files.map(row => row.id)} disabled={!!busy} onAdd={addDocuments} onRemove={id => { setFiles(previous => previous.filter(row => row.id !== id)); change({ ...input, documents: input.documents.filter(row => row.id !== id) }) }} />
    <div className="form-field"><span>挂载资源（本次调试关联，只读确认）</span>{mountedResources.map(row => <div className="resource-row" key={row.id}><span>{row.name}</span><span className="status-tag blue">已挂载</span></div>)}{!mountedResources.length && <p className="helper-text">未挂载资源</p>}</div>
    <div ref={resultRef}><DebugResult result={item.debug} running={running} downloading={busy === 'document'} onRetry={item.debug?.runId ? retryDocument : undefined} /></div>
    {!realtimeDebugEnabled && <details className="simulation-options"><summary>模拟调试场景</summary><select aria-label="模拟调试场景" disabled={!!busy} value={scenario} onChange={event => { setScenario(event.target.value); onResult(undefined) }}><option value="passed">执行成功</option><option value="failed">执行失败</option><option value="timeout">执行超时</option></select></details>}
    <p className="helper-text">{realtimeDebugEnabled ? '运行调试将提交 Skill 定义、对话输入与原始文件；完成后可下载真实 Excel 结果。最多10份需求文档、20份挂载资源。' : '当前为模拟调试，输出可下载的 Markdown 文档，最多10条；未解析文件或执行脚本。'}</p>
    {error && editor === null && <p className="error-banner" role="alert">{error}</p>}
  </Dialog>{editor !== null && <Dialog wide title="编辑 Skill 定义（Markdown）" busy={!!busy} onClose={closeEditor} footer={discard ? <><span role="alert">存在未保存修改，确认放弃？</span><button className="button" onClick={() => setDiscard(false)}>继续编辑</button><button className="button danger" onClick={() => { setEditor(null); setDiscard(false) }}>放弃修改</button></> : <><button className="button" disabled={!!busy} onClick={closeEditor}>取消</button><button className="button primary" disabled={!!busy} onClick={saveDefinition}>{busy ? '保存中…' : '保存'}</button></>}><p className="helper-text">保存后同步至我创建的技能，系统递增版本并使旧调试结果失效。版本由系统管理。</p><textarea className="markdown-editor" aria-label="Markdown Skill 定义" maxLength={200000} value={editor} disabled={!!busy} onChange={event => setEditor(event.target.value)} spellCheck={false} />{error && <p className="error-banner" role="alert">{error}</p>}</Dialog>}</>
}
