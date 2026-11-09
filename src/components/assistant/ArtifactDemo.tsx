import { useState } from 'react'
import { exportArtifact, getArtifact, openArtifactDemo, saveArtifact } from '@/api/assistantArtifacts'
import { assetSourceStatus, createAsset, downloadAsset, getAssetOverview, type AssetStatus, type AssetOverview } from '@/api/assets'
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
  classId: string
  visibility: 'private' | 'platform'
}

export default function ArtifactDemo() {
  const [artifact, setArtifact] = useState<AssistantArtifact>()
  const [kind, setKind] = useState('test_cases')
  const [artifactIds, setArtifactIds] = useState<Record<string, string>>({})
  const [exportChoice, setExportChoice] = useState<ArtifactFile>()
  const [form, setForm] = useState<ArchiveForm>()
  const [applications, setApplications] = useState<DeveloperCatalogOption[]>([])
  const [classes, setClasses] = useState<AssetOverview['classes']>([])
  const [assetStatus, setAssetStatus] = useState<AssetStatus>()
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
      setArtifactIds(previous => ({ ...previous, [kind]: current.artifactId }))
      setArtifact(current)
      setAssetStatus(undefined)
      setAssetStatus(await assetSourceStatus(current.artifactId))
    })
  }

  function chooseExport(current: ArtifactFile) {
    return run(async () => {
      const status = await assetSourceStatus(current.artifactId)
      setAssetStatus(status)
      if (status.included) await exportArtifact(current)
      else setExportChoice(current)
    })
  }

  function beginArchive(current: ArtifactFile, exportAfter: boolean) {
    return run(async () => {
      const [metadata, overview] = await Promise.all([getDeveloperMetadata(), getAssetOverview()])
      setApplications(metadata.applications.filter(application => application.id !== '*'))
      setClasses(overview.classes.filter(row => row.enabled))
      setForm({ artifact: current, exportAfter, name: current.name, application: '', classId: '', visibility: 'private' })
      setExportChoice(undefined)
    })
  }

  function submit(form: ArchiveForm) {
    return run(async () => {
      const status = await createAsset({ artifact_id: form.artifact.artifactId, base_hash: form.artifact.baseHash,
        name: form.name.trim(), application_identify: form.application, skill_classes_id: Number(form.classId), visibility: form.visibility })
      setAssetStatus(status)
      setForm(undefined)
      window.dispatchEvent(new Event('asset-collection-changed'))
      if (form.exportAfter && status.asset_id && status.files.length === 1) await downloadAsset(status.asset_id, status.files[0])
    })
  }

  const drawerProps = {
    actionBusy: busy, actionError: exportChoice || form ? '' : error,
    onClose: () => { setArtifact(undefined); setError('') },
    toolbar: (saved: ArtifactFile, disabled: boolean) => <>
      <button type="button" className="button" disabled={disabled} onClick={() => void chooseExport(saved)}>导出</button>
      <button type="button" className="button primary" disabled={disabled || !!assetStatus?.included || !!assetStatus?.recycled}
        onClick={() => void beginArchive(saved, false)}>{assetStatus?.included ? '已纳入资产管理' : assetStatus?.recycled ? '资产在回收站' : '纳入资产管理'}</button>
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
        <button type="button" className="button primary" disabled={busy || assetStatus?.recycled} onClick={() => void beginArchive(exportChoice, true)}>纳入资产并导出</button></>}>
      <p>{assetStatus?.recycled ? '产出物已在回收站，可仅导出原件，或在资产管理中恢复。' : '当前产出物尚未纳入资产管理，是否将整份产出物纳入后再导出？'}</p>
      {error && <p className="error-banner" role="alert">{error}</p>}
    </Dialog>}
    {form && <Dialog title="纳入资产管理" busy={busy} onClose={() => { setForm(undefined); setError('') }}
      footer={<><button type="button" className="button" disabled={busy} onClick={() => { setForm(undefined); setError('') }}>取消</button>
        <button type="button" className="button primary" disabled={busy || !form.name.trim() || !form.application || !form.classId} onClick={() => void submit(form)}>确认纳入</button></>}>
      <div className="artifact-case-editor">
        <label>资产名称<input value={form.name} maxLength={128} disabled={busy} onChange={event => setForm({ ...form, name: event.target.value })} /></label>
        <label>技能大类<select value={form.classId} disabled={busy} onChange={event => setForm({ ...form, classId: event.target.value })}>
          <option value="">请选择技能大类</option>{classes.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <ApplicationPicker required value={form.application ? [form.application] : []} options={applications}
          disabled={busy} onChange={ids => setForm({ ...form, application: ids[0] ?? '' })} />
        <label>可见范围<select value={form.visibility} disabled={busy}
          onChange={event => setForm({ ...form, visibility: event.target.value === 'platform' ? 'platform' : 'private' })}>
          <option value="private">仅本人</option><option value="platform">全平台</option>
        </select></label>
      </div>
      {error && <p className="error-banner" role="alert">{error}</p>}
    </Dialog>}
  </>
}
