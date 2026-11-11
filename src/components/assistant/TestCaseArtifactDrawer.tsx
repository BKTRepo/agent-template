import { useMemo, useState, type ReactNode } from 'react'
import Dialog from '@/components/developer/Dialog'
import CaseMindMap from './CaseMindMap'
import type { TestCase, TestCaseArtifact } from '@/types/assistantArtifact'

interface Props {
  artifact: TestCaseArtifact
  onSave: (change: Pick<TestCaseArtifact, 'artifactId' | 'baseHash' | 'cases'>) => Promise<TestCaseArtifact>
  onClose: () => void
  toolbar: (saved: TestCaseArtifact, disabled: boolean) => ReactNode
  actionBusy: boolean
  actionError: string
}

export default function TestCaseArtifactDrawer({ artifact, onSave, onClose, toolbar, actionBusy, actionError }: Props) {
  const [saved, setSaved] = useState(artifact)
  const [cases, setCases] = useState(artifact.cases)
  const [view, setView] = useState<'map' | 'list'>('map')
  const [selectedId, setSelectedId] = useState<string>()
  const [editing, setEditing] = useState<TestCase>()
  const [pendingDelete, setPendingDelete] = useState<TestCase>()
  const [discard, setDiscard] = useState<'reset' | 'close'>()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const blocked = saving || actionBusy
  const dirty = JSON.stringify(cases) !== JSON.stringify(saved.cases)
  const groups = useMemo(() => {
    const byId = new Map(cases.map(item => [item.id, item]))
    return saved.groups.map(({ title, caseIds }) => ({
      title, items: caseIds.flatMap(id => { const item = byId.get(id); return item ? [item] : [] }),
    })).filter(group => group.items.length)
  }, [cases, saved.groups])

  async function save() {
    if (blocked || !dirty) return
    setSaving(true)
    setError('')
    try {
      const updated = await onSave({ artifactId: saved.artifactId, baseHash: saved.baseHash, cases })
      setSaved(updated)
      setCases(updated.cases)
      setSelectedId(undefined)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存修改失败，请重试。')
    } finally {
      setSaving(false)
    }
  }

  function actions(item: TestCase) {
    return <div className="artifact-case-actions">
      <button type="button" disabled={blocked} onClick={() => setEditing(item)}>编辑</button>
      <button type="button" className="artifact-case-danger" disabled={blocked} onClick={() => setPendingDelete(item)}>删除</button>
    </div>
  }

  return <>
    <Dialog title={<span className="artifact-case-title">测试产出物<small>{saved.name} · Excel (.xlsx)</small></span>}
      className="artifact-case-drawer" busy={blocked} onClose={() => dirty ? setDiscard('close') : onClose()}
      footer={<><span className={dirty ? 'artifact-case-dirty' : 'helper-text'} role="status">{dirty ? '有未保存的修改' : '已保存'}</span>
        <button type="button" className="button" disabled={!dirty || blocked} onClick={() => setDiscard('reset')}>取消修改</button>
        <button type="button" className="button primary" disabled={!dirty || blocked} onClick={() => void save()}>{saving ? '保存中…' : '保存修改'}</button></>}>
      <div className="artifact-case-views">
        <div role="group" aria-label="测试案例视图">
        <button type="button" aria-pressed={view === 'map'} onClick={() => setView('map')}>思维导图</button>
        <button type="button" aria-pressed={view === 'list'} onClick={() => setView('list')}>用例</button>
        </div>
        <div className="artifact-case-toolbar">{toolbar(saved, dirty || blocked)}</div>
      </div>
      {(error || actionError) && <p className="error-banner artifact-case-error" role="alert">{error || actionError}</p>}
      {saved.groupingError && <p className="error-banner" role="alert">{saved.groupingError}</p>}
      {!groups.length ? <p className="empty-table">暂无测试案例</p> : view === 'map' ?
        <CaseMindMap title={saved.name} groups={groups} selectedId={selectedId} disabled={blocked}
          onSelect={id => { setSelectedId(id); setEditing(cases.find(item => item.id === id)) }} actions={actions} /> :
        <div className="artifact-case-list">{groups.map(({ title, items }) => <section key={title}>
        <h3>{title}</h3>
        {items.map(item => <article key={item.id}>
          <header><h4>{item.name}</h4>{actions(item)}</header>
          <dl><dt>前置条件</dt><dd>{item.preconditions || '—'}</dd></dl>
          <ol>{item.steps.map(step => <li key={step.id}>{step.action}
            {step.expected != null && <p>预期结果 · {step.expected || '—'}</p>}</li>)}</ol>
          {item.expected != null && <dl><dt>预期结果</dt><dd>{item.expected || '—'}</dd></dl>}
        </article>)}
      </section>)}</div>}
    </Dialog>

    {editing && <Dialog className="assistant-owned-dialog" title="编辑测试案例" onClose={() => setEditing(undefined)}
      footer={<><button type="button" className="button" onClick={() => setEditing(undefined)}>取消</button>
        <button type="submit" form="artifact-case-edit" className="button primary" disabled={!editing.name.trim()}>确认编辑</button></>}>
      <form id="artifact-case-edit" className="artifact-case-editor" onSubmit={event => {
        event.preventDefault()
        if (!editing.name.trim()) return
        setCases(previous => previous.map(item => item.id === editing.id ? { ...editing, name: editing.name.trim() } : item))
        setEditing(undefined)
      }}>
        <label>案例名称<input required value={editing.name} onChange={event => setEditing({ ...editing, name: event.target.value })} /></label>
        <label>前置条件<textarea aria-label="前置条件" value={editing.preconditions} onChange={event => setEditing({ ...editing, preconditions: event.target.value })} /></label>
        {editing.steps.map((step, index) => <fieldset key={step.id}>
          <legend>步骤 {index + 1}</legend>
          <label>操作内容<textarea aria-label={`操作内容 ${index + 1}`} value={step.action} onChange={event => setEditing({ ...editing, steps: editing.steps.map((row, position) => position === index ? { ...row, action: event.target.value } : row) })} /></label>
          {step.expected != null && <label>本步骤预期结果<textarea value={step.expected} onChange={event => setEditing({ ...editing, steps: editing.steps.map((row, position) => position === index ? { ...row, expected: event.target.value } : row) })} /></label>}
          <button type="button" className="button small" aria-label={`删除步骤 ${index + 1}`} onClick={() => setEditing({ ...editing, steps: editing.steps.filter((_, position) => position !== index) })}>删除步骤</button>
        </fieldset>)}
        {editing.expected != null && <label>预期结果<textarea aria-label="预期结果" value={editing.expected} onChange={event => setEditing({ ...editing, expected: event.target.value })} /></label>}
      </form>
    </Dialog>}

    {pendingDelete && <Dialog className="assistant-owned-dialog" title="删除测试案例" onClose={() => setPendingDelete(undefined)}
      footer={<><button type="button" className="button" onClick={() => setPendingDelete(undefined)}>取消</button>
        <button type="button" className="button primary" onClick={() => {
          setCases(previous => previous.filter(item => item.id !== pendingDelete.id))
          setSelectedId(undefined)
          setPendingDelete(undefined)
        }}>确认删除</button></>}>
      <p>删除「{pendingDelete.name}」？点击「保存修改」后才会写入原文件。</p>
    </Dialog>}

    {discard && <Dialog className="assistant-owned-dialog" title="放弃未保存的修改" onClose={() => setDiscard(undefined)}
      footer={<><button type="button" className="button" onClick={() => setDiscard(undefined)}>继续编辑</button>
        <button type="button" className="button primary" onClick={() => {
          if (discard === 'close') { onClose(); return }
          setCases(saved.cases)
          setSelectedId(undefined)
          setError('')
          setDiscard(undefined)
        }}>放弃修改</button></>}>
      <p>放弃后将恢复上次保存的内容。</p>
    </Dialog>}
  </>
}
