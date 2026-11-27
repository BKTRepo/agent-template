import { useEffect, useState } from 'react'
import { exportArtifact, exportOriginalArtifact, getArtifact, saveArtifact } from '@/api/assistantArtifacts'
import { assetSourceStatus, createAsset, downloadAsset, type AssetStatus } from '@/api/assets'
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
}

export function ArchiveStageField({ skillClass }: { skillClass?: DeveloperCatalogOption }) {
  return <label>测试阶段<input aria-label="自动关联的测试阶段" readOnly value={skillClass ? skillClass.test_stage_name || '阶段未配置' : ''}
    placeholder="选择技能大类后自动关联" /><small className="helper-text">根据所选技能大类自动关联</small></label>
}

export default function ArtifactWorkbench({ artifactId, fileName, onClose }: { artifactId: string; fileName: string; onClose: () => void }) {
  const [artifact, setArtifact] = useState<AssistantArtifact>()
  const [exportChoice, setExportChoice] = useState<ArtifactFile>()
  const [form, setForm] = useState<ArchiveForm>()
  const [applications, setApplications] = useState<DeveloperCatalogOption[]>([])
  const [classes, setClasses] = useState<DeveloperCatalogOption[]>([])
  const [assetStatus, setAssetStatus] = useState<AssetStatus>()
  const [previewLoading, setPreviewLoading] = useState(true)
  const [previewError, setPreviewError] = useState('')
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
    setArtifact(undefined); setAssetStatus(undefined); setPreviewError(''); setPreviewLoading(true)
    void getArtifact(artifactId, controller.signal).then(current => {
      if (!controller.signal.aborted) setArtifact(current)
    }).catch(reason => { if (!controller.signal.aborted) setPreviewError((reason as Error).message) })
      .finally(() => { if (!controller.signal.aborted) setPreviewLoading(false) })
    void assetSourceStatus(artifactId, controller.signal).then(status => {
      if (!controller.signal.aborted) setAssetStatus(current => current ?? status)
    }).catch(() => {})
    return () => controller.abort()
  }, [artifactId, reload])

  function chooseExport(current: ArtifactFile) {
    return run(async () => {
      if (assetStatus?.included) await exportArtifact(current)
      else setExportChoice(current)
    })
  }

  function beginArchive(current: ArtifactFile, exportAfter: boolean) {
    return run(async () => {
      const metadata = await getDeveloperMetadata()
      setApplications(metadata.applications.filter(application => application.id !== '*'))
      setClasses(metadata.skill_classes)
      setForm({ artifact: current, exportAfter, name: current.name, application: '', classId: '' })
      setExportChoice(undefined)
    })
  }

  function submit(form: ArchiveForm) {
    return run(async () => {
      const status = await createAsset({ artifact_id: form.artifact.artifactId, base_hash: form.artifact.baseHash,
        name: form.name.trim(), application_identify: form.application, skill_classes_id: Number(form.classId) })
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
    {!artifact && <Dialog className="assistant-owned-dialog" title="测试产出物" busy={previewLoading || busy} closeWhileBusy onClose={onClose}
      footer={<><button className="button" onClick={onClose}>关闭</button>
        {previewError && <button className="button" disabled={busy} onClick={() => setReload(value => value + 1)}>重试</button>}
        <button className="button primary" disabled={busy} onClick={() => void run(() => exportOriginalArtifact(artifactId, fileName))}>
          {busy ? '正在导出…' : '仅导出原文件'}
        </button></>}>
      {previewLoading && <p role="status">正在读取产出物…</p>}
      {previewError && <p role="alert" className="error-banner">{previewError}</p>}
      {error && <p role="alert" className="error-banner">{error}</p>}
    </Dialog>}
    {artifact && (artifact.editor === 'cases'
      ? <TestCaseArtifactDrawer artifact={artifact} checkArchived={async id => {
        const status = await assetSourceStatus(id)
        setAssetStatus(status)
        return status.included
      }} onSave={async change => {
        const updated = await saveArtifact(change)
        if (change.syncAsset) window.dispatchEvent(new Event('asset-collection-changed'))
        return updated
      }} {...drawerProps} />
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
        <ArchiveStageField skillClass={classes.find(row => row.id === form.classId)} />
        <ApplicationPicker required value={form.application ? [form.application] : []} options={applications}
          disabled={busy} onChange={ids => setForm({ ...form, application: ids[0] ?? '' })} />
      </div>
      {error && <p className="error-banner" role="alert">{error}</p>}
    </Dialog>}
  </>
}
