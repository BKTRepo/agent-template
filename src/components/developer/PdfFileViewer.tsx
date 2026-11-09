import { useEffect, useRef, useState } from 'react'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.mjs?url'

export default function PdfFileViewer({ blob, zoom, fit }: { blob: Blob; zoom: number; fit: boolean }) {
  const [document, setDocument] = useState<PDFDocumentProxy>()
  const [page, setPage] = useState(1), [width, setWidth] = useState(700), [error, setError] = useState(''), [rendering, setRendering] = useState(false)
  const container = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const element = container.current
    if (!element) return
    const observer = new ResizeObserver(() => setWidth(Math.max(200, element.clientWidth - 48)))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    let canceled = false, task: { destroy: () => Promise<void> } | undefined
    setDocument(undefined); setError(''); setPage(1)
    void (async () => {
      const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
      if (canceled) return
      const bytes = new Uint8Array(await blob.arrayBuffer())
      if (canceled) return
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
      const loading = pdfjs.getDocument({ data: bytes,
        cMapUrl: '/pdfjs/cmaps/', cMapPacked: true, standardFontDataUrl: '/pdfjs/standard_fonts/', wasmUrl: '/pdfjs/wasm/' })
      task = loading
      const result = await loading.promise
      if (!canceled) setDocument(result)
    })().catch(reason => { if (!canceled) setError(`PDF 无法预览：${(reason as Error).message}。可下载原文件查看。`) })
    return () => { canceled = true; void task?.destroy().catch(() => {}) }
  }, [blob])
  useEffect(() => {
    if (!document || !canvas.current) return
    let canceled = false, task: RenderTask | undefined
    setRendering(true); setError('')
    void document.getPage(page).then(pdfPage => {
      if (canceled || !canvas.current) return
      const natural = pdfPage.getViewport({ scale: 1 })
      const scale = (fit ? Math.min(width / natural.width, 3) : zoom / 100)
      const viewport = pdfPage.getViewport({ scale })
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      const target = canvas.current
      target.width = Math.ceil(viewport.width * ratio); target.height = Math.ceil(viewport.height * ratio)
      target.style.width = `${viewport.width}px`; target.style.height = `${viewport.height}px`
      task = pdfPage.render({ canvas: target, viewport, transform: [ratio, 0, 0, ratio, 0, 0] })
      return task.promise
    }).catch(reason => { if (!canceled) setError((reason as Error).message) }).finally(() => { if (!canceled) setRendering(false) })
    return () => { canceled = true; task?.cancel() }
  }, [document, page, zoom, fit, width])
  return <div className="pdf-file-viewer" ref={container}>
    <div className="preview-page-controls"><button className="button small" disabled={!document || page <= 1 || rendering} onClick={() => setPage(value => value - 1)}>上一页</button>
      <label>页码 <input aria-label="PDF页码" type="number" min={1} max={document?.numPages || 1} value={page} onChange={event => setPage(Math.max(1, Math.min(document?.numPages || 1, Number(event.target.value) || 1)))} /></label>
      <span>/ {document?.numPages ?? '—'}</span><button className="button small" disabled={!document || page >= document.numPages || rendering} onClick={() => setPage(value => value + 1)}>下一页</button>
      {rendering && <span role="status">正在绘制页面…</span>}</div>
    {error ? <p role="alert" className="error-banner">{error}</p> : <div className="pdf-page-stage">{!document && <p role="status">正在加载PDF…</p>}<canvas ref={canvas} aria-label={`PDF第${page}页`} /></div>}
  </div>
}
