import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { downloadAsset, getAsset, previewAsset, previewAssetPdf, previewAssetSheet, type AssetDetail, type AssetPreview } from '@/api/assets'
import CaseMindMap from '@/components/assistant/CaseMindMap'
import Dialog from '@/components/developer/Dialog'
import PdfFileViewer from '@/components/developer/PdfFileViewer'
import SpreadsheetFileViewer from '@/components/developer/SpreadsheetFileViewer'

const CodeEditor = lazy(() => import('@/components/assistant/ArtifactCodeEditor'))

function AssetCases({ cases }: { cases: NonNullable<AssetPreview['case_artifact']> }) {
  const [selected, setSelected] = useState<string>()
  const groups = useMemo(() => {
    const byId = new Map(cases.cases.map(item => [item.id, item]))
    return cases.groups.map(group => ({ title: group.title, items: group.case_ids.flatMap(id => byId.get(id) ?? []) }))
  }, [cases])
  if (!groups.length) return <p className="empty-table">暂无测试案例</p>
  return <CaseMindMap title={cases.name} groups={groups} selectedId={selected} disabled={false}
    onSelect={id => setSelected(id === selected ? undefined : id)} actions={item => <div className="asset-case-detail">
      <b>前置条件</b><p>{item.preconditions || '—'}</p><ol>{item.steps.map(step => <li key={step.id}>{step.action}
        {step.expected && <p>预期结果 · {step.expected}</p>}</li>)}</ol><b>预期结果</b><p>{item.expected || '—'}</p>
    </div>} />
}

export default function AssetPreviewDialog({ assetId, onClose }: { assetId: number; onClose: () => void }) {
  const [asset, setAsset] = useState<AssetDetail>()
  const [fileId, setFileId] = useState<number>()
  const [preview, setPreview] = useState<AssetPreview>()
  const [pdf, setPdf] = useState<Blob>()
  const [zoom, setZoom] = useState(100)
  const [fit, setFit] = useState(true)
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [downloadError, setDownloadError] = useState('')
  const [downloading, setDownloading] = useState(false)
  const file = asset?.files.find(row => row.id === fileId)
  useEffect(() => {
    const controller = new AbortController()
    void getAsset(assetId, controller.signal).then(value => {
      if (controller.signal.aborted) return
      setAsset(value); setFileId(value.files[0]?.id); setLoading(Boolean(value.files.length))
    }).catch(reason => { if (!controller.signal.aborted) { setError(reason.message); setLoading(false) } })
    return () => controller.abort()
  }, [assetId])

  useEffect(() => {
    if (!fileId) return
    const controller = new AbortController()
    setLoading(true); setPreview(undefined); setPdf(undefined); setError(''); setZoom(100); setFit(true)
    void (async () => {
      const value = await previewAsset(assetId, fileId, controller.signal)
      const document = value.viewer === 'pdf' ? await previewAssetPdf(assetId, fileId, controller.signal) : undefined
      if (!controller.signal.aborted) { setPreview(value); setPdf(document) }
    })().catch(reason => { if (!controller.signal.aborted) setError(reason.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [assetId, fileId])

  const sheet = useCallback((index: number, row: number, column: number, signal: AbortSignal) =>
    previewAssetSheet(assetId, fileId!, index, row, column, signal), [assetId, fileId])

  async function download() {
    if (!file || downloading) return
    setDownloading(true); setDownloadError('')
    try { await downloadAsset(assetId, file) }
    catch (reason) { setDownloadError((reason as Error).message) }
    finally { setDownloading(false) }
  }

  return <Dialog title={asset?.name ?? '资产预览'} onClose={onClose} className={`asset-preview-drawer ${expanded ? 'expanded' : ''}`}
    footer={<><button className="button" onClick={onClose}>关闭</button>
      <button className="button primary" disabled={!file || downloading} onClick={() => void download()}>下载原文件</button></>}>
    {asset && <div className="asset-preview-meta"><span>资产 #{asset.id}</span><span>{asset.class_name}</span><span>{asset.creator_name}</span><span>{asset.visibility === 'private' ? '仅本人' : '全平台'}</span></div>}
    <div className="asset-preview-toolbar">
      {file && <label>附件 <select value={file.id} onChange={event => setFileId(Number(event.target.value))}>
        {asset?.files.map(row => <option key={row.id} value={row.id}>{row.file_name}</option>)}</select></label>}
      {(preview?.viewer === 'pdf' || preview?.viewer === 'spreadsheet') && <label>缩放 <select value={zoom} onChange={event => { setZoom(Number(event.target.value)); setFit(false) }}>
        {[50, 75, 100, 125, 150, 200].map(value => <option key={value} value={value}>{value}%</option>)}</select></label>}
      <button className="button small" onClick={() => setExpanded(!expanded)}>{expanded ? '退出全屏' : '全屏预览'}</button>
    </div>
    {downloadError && <p role="alert" className="error-banner">{downloadError}</p>}
    <div className="asset-preview-content" aria-busy={loading}>
      {loading ? <p role="status">正在加载原文件…</p> : error ? <p role="alert" className="error-banner">{error}</p>
        : preview?.viewer === 'case' && preview.case_artifact ? <AssetCases key={fileId} cases={preview.case_artifact} />
        : preview?.viewer === 'pdf' && pdf ? <PdfFileViewer blob={pdf} zoom={zoom} fit={fit} />
        : preview?.viewer === 'spreadsheet' && preview.sheets && fileId ? <SpreadsheetFileViewer key={fileId}
          metadata={{ id: fileId, generation: 1, sheets: preview.sheets }} zoom={zoom} loadPage={sheet} />
        : preview?.viewer === 'code' ? <Suspense fallback={<p role="status">正在加载脚本预览…</p>}>
          <CodeEditor key={fileId} text={preview.text ?? ''} type={preview.format} readOnly onChange={() => {}} />
        </Suspense>
        : preview?.viewer === 'markdown' ? <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]}
          components={{ img: ({ alt }) => <span>{alt || '图片'}</span>, a: ({ children }) => <span>{children}</span> }}>{preview.text ?? ''}</ReactMarkdown>
        : preview?.viewer === 'text' ? <pre className="preview-plain-text">{preview.text || '文件内容为空'}</pre>
        : <p className="helper-text">该文件暂无在线预览，可下载原文件查看。</p>}
      {preview?.truncated && <p className="helper-text">当前预览前 512 KB，可下载完整文件。</p>}
    </div>
  </Dialog>
}
