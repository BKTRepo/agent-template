import { useState } from 'react'
import { archiveArtifact, artifactAssetStatus, exportArtifact, getArtifact, openArtifactDemo, saveArtifact } from '@/api/assistantArtifacts'
import { getDeveloperMetadata, type DeveloperCatalogOption } from '@/api/developerCenter'
import ApplicationPicker from '@/components/developer/ApplicationPicker'
import Dialog from '@/components/developer/Dialog'
import type { ArtifactFile, AssistantArtifact } from '@/types/assistantArtifact'
import TestCaseArtifactDrawer from './TestCaseArtifactDrawer'
import ArtifactFileDrawer from './ArtifactFileDrawer'

const demoKinds = [
  ['test_cases', '测试案例导图'], ['docx', '测试报告 DOCX'], ['xlsx', '测试数据 XLSX'], ['py', 'Python 脚本'],
  ['js', 'JavaScript 脚本'], ['ts', 'TypeScript 脚本'], ['sh', 'Shell 脚本'], ['sql', 'SQL 脚本'],
  ['md', 'Markdown 文档'], ['json', 'JSON 数据'],
]

interface ArchiveForm {
  artifact: ArtifactFile
  exportAfter: boolean
  name: string
  application: string
}

export default function ArtifactDemo() {
  const [artifact, setArtifact] = useState<AssistantArtifact>()
  const [kind, setKind] = useState('test_cases')
  const [artifactIds, setArtifactIds] = useState<Record<string, string>>({})
  const [exportChoice, setExportChoice] = useState<ArtifactFile>()
  const [form, setForm] = useState<ArchiveForm>()
  const [applications, setApplications] = useState<DeveloperCatalogOption[]>([])
  const [included, setIncluded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function run(action: () => Promise<void>) {
    if (busy) return
    setBusy(true)
    setError('')
    try { await action() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败，请重试。') }
    finally { setBusy(false) }
  }

  function open() {
    return run(async () => {
      const artifactId = artifactIds[kind]
      const current = artifactId ? await getArtifact(artifactId) : await openArtifactDemo(kind)
      const status = await artifactAssetStatus(current.artifactId)
      setArtifactIds(previous => ({ ...previous, [kind]: current.artifactId }))
      setIncluded(status.included)
      setArtifact(current)
    })
  }

  function chooseExport(current: ArtifactFile) {
    return run(async () => {
      const status = await artifactAssetStatus(current.artifactId)
      setIncluded(status.included)
      if (status.included) await exportArtifact(current)
      else setExportChoice(current)
    })
  }

  function beginArchive(current: ArtifactFile, exportAfter: boolean) {
    return run(async () => {
      const metadata = await getDeveloperMetadata()
      setApplications(metadata.applications.filter(application => application.id !== '*'))
      setForm({ artifact: current, exportAfter, name: current.name, application: '' })
      setExportChoice(undefined)
    })
  }

  function submit(form: ArchiveForm) {
    return run(async () => {
      const status = await archiveArtifact(form.artifact, form.name.trim(), form.application)
      setIncluded(true)
      setForm(undefined)
      if (form.exportAfter) {
        await exportArtifact(form.artifact, status.file_sha256 === form.artifact.baseHash)
      }
    })
  }

  const drawerProps = {
    actionBusy: busy, actionError: exportChoice || form ? '' : error,
    onClose: () => { setArtifact(undefined); setError('') },
    toolbar: (saved: ArtifactFile, disabled: boolean) => <>
      <button type="button" className="button" disabled={disabled} onClick={() => void chooseExport(saved)}>导出</button>
      <button type="button" className="button primary" disabled={disabled || included} onClick={() => void beginArchive(saved, false)}>{included ? '已纳入样例资产' : '纳入资产管理'}</button>
    </>,
  }

  return <>
    <div className="assistant-artifact-entry">
      <select aria-label="产出物样例类型" value={kind} disabled={busy} onChange={event => setKind(event.target.value)}>
        {demoKinds.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
      </select>
      <button type="button" className="button small" disabled={busy} onClick={() => void open()}>{kind === 'test_cases' ? '打开测试案例样例' : '打开产出物样例'}</button>
      {error && !artifact && <span role="alert" className="platform-field-error">{error}</span>}
    </div>
    {artifact && (artifact.editor === 'cases'
      ? <TestCaseArtifactDrawer artifact={artifact} onSave={saveArtifact} {...drawerProps} />
      : <ArtifactFileDrawer artifact={artifact} {...drawerProps} />)}
    {exportChoice && <Dialog title="导出测试产出物" busy={busy}
      onClose={() => { setExportChoice(undefined); setError('') }}
      footer={<><button type="button" className="button" disabled={busy} onClick={() => void run(async () => {
        await exportArtifact(exportChoice)
        setExportChoice(undefined)
      })}>仅导出</button>
        <button type="button" className="button primary" disabled={busy} onClick={() => void beginArchive(exportChoice, true)}>纳入资产并导出</button></>}>
      <p>当前产出物尚未纳入资产管理，是否将整份产出物纳入后再导出？</p>
      {error && <p className="error-banner" role="alert">{error}</p>}
    </Dialog>}
    {form && <Dialog title="纳入资产管理" busy={busy} onClose={() => { setForm(undefined); setError('') }}
      footer={<><button type="button" className="button" disabled={busy} onClick={() => { setForm(undefined); setError('') }}>取消</button>
        <button type="button" className="button primary" disabled={busy || !form.name.trim() || !form.application} onClick={() => void submit(form)}>确认纳入</button></>}>
      <p className="helper-text">联调样例，归档快照保存在样例共享目录。</p>
      <div className="artifact-case-editor">
        <label>资产名称<input value={form.name} maxLength={128} disabled={busy} onChange={event => setForm({ ...form, name: event.target.value })} /></label>
        <p>资产分类 · {artifact?.editor === 'cases' ? '测试用例' : ['docx', 'md'].includes(form.artifact.fileType) ? '测试报告' : ['xlsx', 'json'].includes(form.artifact.fileType) ? '测试数据' : '自动化脚本'}</p>
        <ApplicationPicker required value={form.application ? [form.application] : []} options={applications}
          disabled={busy} onChange={ids => setForm({ ...form, application: ids[0] ?? '' })} />
      </div>
      {error && <p className="error-banner" role="alert">{error}</p>}
    </Dialog>}
  </>
}
