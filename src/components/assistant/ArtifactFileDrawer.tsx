import { lazy, Suspense, useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { saveOrdinaryArtifact } from '@/api/assistantArtifacts'
import Dialog from '@/components/developer/Dialog'
import type { ArtifactFile, CellEdit, FileChanges, OrdinaryArtifact } from '@/types/assistantArtifact'
import ArtifactWordContent from './ArtifactWordContent'
import ArtifactSpreadsheet from './ArtifactSpreadsheet'

const CodeEditor = lazy(() => import('./ArtifactCodeEditor'))

export default function ArtifactFileDrawer({ artifact, onClose, toolbar, actionBusy, actionError }: {
  artifact: OrdinaryArtifact
  onClose: () => void
  toolbar: (saved: ArtifactFile, disabled: boolean) => ReactNode
  actionBusy: boolean
  actionError: string
}) {
  const [saved, setSaved] = useState(artifact)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState<string>()
  const [paragraphs, setParagraphs] = useState<Record<string, string>>({})
  const [cells, setCells] = useState<Record<string, CellEdit>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [discard, setDiscard] = useState<'reset' | 'close'>()
  const blocked = actionBusy || saving
  const dirty = text !== undefined || Object.keys(paragraphs).length > 0 || Object.keys(cells).length > 0

  function reset() {
    setText(undefined); setParagraphs({}); setCells({}); setError(''); setEditing(false)
  }

  async function save() {
    if (!dirty || blocked) return
    let changes: FileChanges
    switch (saved.editor) {
      case 'word': changes = { paragraphs: Object.entries(paragraphs).map(([id, text]) => ({ id, text })) }; break
      case 'sheet': changes = { cells: Object.values(cells) }; break
      case 'text': changes = { text: text ?? saved.text }; break
    }
    setSaving(true)
    setError('')
    try {
      setSaved(await saveOrdinaryArtifact(saved, changes))
      reset()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存修改失败，请重试。') }
    finally { setSaving(false) }
  }

  return <>
    <Dialog className="artifact-case-drawer ordinary-artifact-drawer" title={
      <span className="artifact-case-title">测试产出物<small>{saved.name}.{saved.fileType}</small></span>}
      busy={blocked} onClose={() => dirty ? setDiscard('close') : onClose()}
      footer={<><span className={dirty ? 'artifact-case-dirty' : 'helper-text'} role="status">{dirty ? '有未保存的修改' : '已保存'}</span>
        <button className="button" type="button" disabled={!dirty || blocked} onClick={() => setDiscard('reset')}>取消修改</button>
        <button className="button primary" type="button" disabled={!dirty || blocked} onClick={() => void save()}>{saving ? '保存中…' : '保存修改'}</button></>}>
      <div className="artifact-case-views">
        <div role="group" aria-label="文件视图">
          <button type="button" aria-pressed={!editing} disabled={blocked} onClick={() => setEditing(false)}>预览</button>
          <button type="button" aria-pressed={editing} disabled={blocked} onClick={() => setEditing(true)}>编辑</button>
        </div>
        <div className="artifact-case-toolbar">{toolbar(saved, dirty || blocked)}</div>
      </div>
      {(error || actionError) && <p className="error-banner artifact-case-error" role="alert">{error || actionError}</p>}
      <div className={`artifact-file-content ${saved.editor}`}>
        {saved.editor === 'word' && <ArtifactWordContent blocks={saved.blocks} changes={paragraphs} editing={editing && !blocked}
          onChange={(id, before, value) => setParagraphs(previous => {
            const updated = { ...previous }
            if (value === before) delete updated[id]
            else updated[id] = value
            return updated
          })} />}
        {saved.editor === 'sheet' && <ArtifactSpreadsheet artifact={saved} editing={editing && !blocked} changes={cells}
          onChange={(edit, original) => setCells(previous => {
            const key = `${edit.sheet_index}:${edit.address}`
            const updated = { ...previous }
            if (edit.type === original.type && edit.value === original.value) delete updated[key]
            else updated[key] = edit
            return updated
          })} />}
        {saved.editor === 'text' && (saved.fileType === 'md' && !editing ?
          <article className="preview-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
            img: ({ alt }) => <span>{alt || '[图片]'}</span>, a: ({ children }) => <span>{children}</span>,
          }}>{text ?? saved.text}</ReactMarkdown></article> :
          <Suspense fallback={<p className="empty-table" role="status">正在加载编辑器…</p>}>
            <CodeEditor type={saved.fileType} text={text ?? saved.text} readOnly={!editing || blocked}
              onChange={value => setText(value === saved.text.replace(/\r\n?/g, '\n') ? undefined : value)} />
          </Suspense>)}
      </div>
    </Dialog>
    {discard && <Dialog className="assistant-owned-dialog" title="放弃未保存的修改" onClose={() => setDiscard(undefined)}
      footer={<><button className="button" onClick={() => setDiscard(undefined)}>继续编辑</button>
        <button className="button primary" onClick={() => {
          if (discard === 'close') onClose()
          else { reset(); setDiscard(undefined) }
        }}>放弃修改</button></>}>
      <p>放弃后将恢复上次保存的内容。</p>
    </Dialog>}
  </>
}
