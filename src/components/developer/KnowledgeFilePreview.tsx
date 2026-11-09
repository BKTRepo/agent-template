import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Dialog from './Dialog'
import PdfFileViewer from './PdfFileViewer'
import SpreadsheetFileViewer from './SpreadsheetFileViewer'
import { useAuthStore } from '@/stores/authStore'
import { downloadBlob } from '@/lib/resourceStorage'
import { getPreviewBinary, getPreviewMetadata, type PreviewMetadata } from '@/api/knowledgePreview'
import type { KnowledgeBase } from '@/types/developer'

export default function KnowledgeFilePreview({ kb, fileId, onClose }: { kb: KnowledgeBase; fileId: string; onClose: () => void }) {
  const [selected, setSelected] = useState(fileId), [metadata, setMetadata] = useState<PreviewMetadata>()
  const [blob, setBlob] = useState<Blob>(), [text, setText] = useState(''), [error, setError] = useState('')
  const [loading, setLoading] = useState(false), [downloading, setDownloading] = useState(false), [nonce, setNonce] = useState(0)
  const [zoom, setZoom] = useState(100), [fit, setFit] = useState(true), [expanded, setExpanded] = useState(false)
  const token = useAuthStore(state => state.session?.token)
  const file = kb.files.find(row => row.id === selected)
  useEffect(() => setSelected(fileId), [fileId])
  useEffect(() => {
    const controller = new AbortController()
    setMetadata(undefined); setBlob(undefined); setText(''); setError(''); setLoading(true); setZoom(100); setFit(true)
    void (async () => {
      const info = await getPreviewMetadata(kb.id, selected, controller.signal)
      if (controller.signal.aborted) return
      setMetadata(info)
      if (['pdf', 'text', 'markdown'].includes(info.viewer)) {
        const original = await getPreviewBinary(kb.id, selected, info.generation, info.viewer === 'pdf', controller.signal)
        if (controller.signal.aborted) return
        setBlob(original)
        if (info.viewer !== 'pdf') {
          const content = await original.slice(0, 512 * 1024).text()
          if (!controller.signal.aborted) setText(content)
        }
      }
    })().catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [kb.id, selected, nonce, token])
  async function download() {
    if (downloading) return
    setDownloading(true)
    try {
      const original = await getPreviewBinary(kb.id, selected, metadata?.generation, false)
      if (useAuthStore.getState().session?.token === token) downloadBlob(original, metadata?.filename || file?.name || 'document')
    } catch (reason) { setError((reason as Error).message) }
    finally { setDownloading(false) }
  }
  const index = kb.files.findIndex(row => row.id === selected)
  const markdownComponents = { img: ({ alt }: { alt?: string }) => <span>{alt ? `[图片：${alt}]` : '[图片]'}</span>, a: ({children}: {children?: React.ReactNode}) => <span>{children}</span> }
  return <Dialog className={`mail-file-preview ${expanded ? 'expanded' : ''}`} title={`文件预览 · ${metadata?.filename || file?.name || ''}`} onClose={onClose} footer={<>
    <span className="preview-footer-count">附件 {index + 1} / {kb.files.length}</span>
    <button className="button" onClick={onClose}>关闭</button><button className="button primary" disabled={downloading || !file} onClick={() => void download()}>{downloading ? '正在下载…' : '下载原文件'}</button>
  </>}>
    <div className="mail-preview-layout"><aside className="preview-attachments" aria-label="知识库附件">{kb.files.map(item => <button key={item.id} className={`preview-attachment ${selected === item.id ? 'active' : ''}`} aria-current={selected === item.id ? 'true' : undefined} onClick={() => setSelected(item.id)}><span>{item.name}</span><small>{(item.size / 1024).toFixed(1)} KB</small></button>)}</aside>
      <section className="mail-preview-main" aria-label="文件内容预览">
        <div className="mail-preview-toolbar"><button className="button small" disabled={index <= 0} onClick={() => setSelected(kb.files[index - 1].id)}>上一个附件</button><button className="button small" disabled={index < 0 || index >= kb.files.length - 1} onClick={() => setSelected(kb.files[index + 1].id)}>下一个附件</button>
          <label>缩放 <select aria-label="预览缩放" value={zoom} onChange={event => { setZoom(Number(event.target.value)); setFit(false) }}>{[50,75,100,125,150,200].map(value => <option key={value} value={value}>{value}%</option>)}</select></label>
          {metadata?.viewer === 'pdf' && <button className={`button small ${fit ? 'primary' : ''}`} onClick={() => setFit(true)}>适应宽度</button>}
          <button className="button small" onClick={() => setExpanded(value => !value)}>{expanded ? '退出全屏' : '全屏预览'}</button>
          <button className="button small" disabled={loading} onClick={() => setNonce(value => value + 1)}>重新加载</button>
        </div>
        <div className="mail-preview-content" aria-busy={loading}>
          {loading ? <p className="preview-loading" role="status">{metadata?.format === 'docx' ? '正在生成Word预览，首次转换可能需要一些时间…' : '正在加载文件预览…'}</p>
              : error ? <p role="alert" className="error-banner">{error}</p>
                : metadata?.viewer === 'pdf' && blob ? <PdfFileViewer blob={blob} zoom={zoom} fit={fit} />
                  : metadata?.viewer === 'spreadsheet' ? <SpreadsheetFileViewer key={`${metadata.id}:${metadata.generation}`} kbId={kb.id} metadata={metadata} zoom={zoom} />
                    : metadata?.viewer === 'markdown' ? <article className="preview-markdown" style={{ fontSize:`${14 * zoom / 100}px` }}><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={markdownComponents}>{text}</ReactMarkdown></article>
                      : metadata?.viewer === 'text' ? <pre className="preview-plain-text" style={{ fontSize:`${14 * zoom / 100}px` }}>{text || '文件内容为空'}</pre>
                        : <p className="helper-text">该格式暂不支持预览，可下载原文件查看。</p>}
          {metadata && ['text','markdown'].includes(metadata.viewer) && (file?.size || 0) > 512 * 1024 && <p className="helper-text">当前预览前512KB，可下载查看完整内容。</p>}
        </div>
      </section>
    </div>
  </Dialog>
}
