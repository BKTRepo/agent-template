import { useEffect, useState, type ReactNode } from 'react'
import { readArtifactFile } from '@/api/assistantArtifacts'
import Dialog from '@/components/developer/Dialog'
import PdfFileViewer from '@/components/developer/PdfFileViewer'
import type { ArtifactFile, DownloadArtifact } from '@/types/assistantArtifact'

export default function ArtifactReadOnlyDrawer({ artifact, onClose, toolbar, actionBusy, actionError }: {
  artifact: DownloadArtifact
  onClose: () => void
  toolbar: (saved: ArtifactFile, disabled: boolean) => ReactNode
  actionBusy: boolean
  actionError: string
}) {
  const [blob, setBlob] = useState<Blob>()
  const [error, setError] = useState('')
  useEffect(() => {
    if (artifact.fileType !== 'pdf') return
    const controller = new AbortController()
    void readArtifactFile(artifact, false, controller.signal).then(value => {
      if (!controller.signal.aborted) setBlob(value)
    }).catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
    return () => controller.abort()
  }, [artifact])
  return <Dialog className="artifact-case-drawer ordinary-artifact-drawer" title={
    <span className="artifact-case-title">测试产出物<small>{artifact.name}.{artifact.fileType}</small></span>}
    busy={actionBusy} onClose={onClose} footer={<button className="button" onClick={onClose} disabled={actionBusy}>关闭</button>}>
    <div className="artifact-case-views"><span>原文件</span><div className="artifact-case-toolbar">{toolbar(artifact, actionBusy)}</div></div>
    {(error || actionError) && <p className="error-banner" role="alert">{error || actionError}</p>}
    {artifact.fileType === 'pdf' ? blob ? <PdfFileViewer blob={blob} zoom={1} fit /> : !error && <p role="status">正在加载 PDF…</p>
      : <p className="empty-table">此格式请导出原文件查看。</p>}
  </Dialog>
}
