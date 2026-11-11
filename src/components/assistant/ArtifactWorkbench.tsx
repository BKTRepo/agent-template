import { useEffect, useState } from 'react'
import { exportArtifact, getArtifact, saveArtifact } from '@/api/assistantArtifacts'
import { assetSourceStatus, createAsset, downloadAsset, getAssetOverview, type AssetStatus, type AssetOverview } from '@/api/assets'
import { getDeveloperMetadata, type DeveloperCatalogOption } from '@/api/developerCenter'
import ApplicationPicker from '@/components/developer/ApplicationPicker'
import Dialog from '@/components/developer/Dialog'
import type { ArtifactFile, AssistantArtifact } from '@/types/assistantArtifact'
import TestCaseArtifactDrawer from './TestCaseArtifactDrawer'
import ArtifactFileDrawer from './ArtifactFileDrawer'
import ArtifactReadOnlyDrawer from './ArtifactReadOnlyDrawer'

interface ArchiveForm {
  artifact: ArtifactFile
  exportAfter: boolean
  name: string
  application: string
  classId: string
  visibility: 'private' | 'platform'
}

export default function ArtifactWorkbench({ artifactId, onClose }: { artifactId: string; onClose: () => void }) {
  const [artifact, setArtifact] = useState<AssistantArtifact>()
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

  const [reload, setReload] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setArtifact(undefined); setAssetStatus(undefined); setError(''); setBusy(true)
    void Promise.all([getArtifact(artifactId, controller.signal), assetSourceStatus(artifactId)]).then(([current, status]) => {
      if (!controller.signal.aborted) { setArtifact(current); setAssetStatus(status) }
    }).catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
      .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [artifactId, reload])

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
    onClose,
    toolbar: (saved: ArtifactFile, disabled: boolean) => <>
      <button type="button" className="button" disabled={disabled} onClick={() => void chooseExport(saved)}>导出</button>
      <button type="button" className="button primary" disabled={disabled || !!assetStatus?.included || !!assetStatus?.recycled}
        onClick={() => void beginArchive(saved, false)}>{assetStatus?.included ? '已纳入资产管理' : assetStatus?.recycled ? '资产在回收站' : '纳入资产管理'}</button>
    </>,
  }

  return <>
    {!artifact && <Dialog className="assistant-owned-dialog" title="测试产出物" busy={busy} closeWhileBusy onClose={onClose}
      footer={<><button className="button" onClick={onClose}>关闭</button>{error && <button className="button primary" onClick={() => setReload(value => value + 1)}>重试</button>}</>}>
      {busy ? <p role="status">正在读取产出物…</p> : <p role="alert" className="error-banner">{error}</p>}
    </Dialog>}
    {artifact && (artifact.editor === 'cases'
      ? <TestCaseArtifactDrawer artifact={artifact} onSave={saveArtifact} {...drawerProps} />
      : artifact.editor === 'download' ? <ArtifactReadOnlyDrawer artifact={artifact} {...drawerProps} /> : <ArtifactFileDrawer artifact={artifact} {...drawerProps} />)}
    {exportChoice && <Dialog className="assistant-owned-dialog" title="导出测试产出物" busy={busy}
      onClose={() => { setExportChoice(undefined); setError('') }}
      footer={<><button type="button" className="button" disabled={busy} onClick={() => void run(async () => {
        await exportArtifact(exportChoice)
        setExportChoice(undefined)
      })}>仅导出</button>
        <button type="button" className="button primary" disabled={busy || assetStatus?.recycled} onClick={() => void beginArchive(exportChoice, true)}>纳入资产并导出</button></>}>
      <p>{assetStatus?.recycled ? '产出物已在回收站，可仅导出原件，或在资产管理中恢复。' : '是否将产出物纳入资产管理'}</p>
      {error && <p className="error-banner" role="alert">{error}</p>}
    </Dialog>}
    {form && <Dialog className="assistant-owned-dialog" title="纳入资产管理" busy={busy} onClose={() => { setForm(undefined); setError('') }}
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
