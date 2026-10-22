import { useEffect, useState } from 'react'
import { Download, FileText, LoaderCircle } from 'lucide-react'
import { readBlob } from '@/lib/resourceStorage'
import type { Implementation } from '@/types/developer'

export default function DebugResult({ result, running, downloading = false, onRetry }: { result: Implementation['debug']; running: boolean; downloading?: boolean; onRetry?: () => void }) {
  const artifact = result?.status === 'passed' ? result.artifact : undefined
  const [file, setFile] = useState<{ key: string; url?: string; size?: number; error?: string }>()

  useEffect(() => {
    if (!artifact) return
    let cancelled = false
    let url: string | undefined
    void readBlob(artifact.key).then(blob => {
      if (cancelled) return
      if (!blob) throw new Error('结果文件已丢失，请重新运行调试生成文档。')
      url = URL.createObjectURL(blob)
      setFile({ key: artifact.key, url, size: blob.size })
    }).catch(error => {
      if (!cancelled) setFile({ key: artifact.key, error: (error as Error).message })
    })
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [artifact])

  const current = file?.key === artifact?.key ? file : undefined
  const isRunning = running || result?.status === 'running'
  return <section className="debug-result" aria-label="输出结果" aria-live="polite" aria-busy={isRunning || downloading}>
    <h3>输出结果</h3>
    {isRunning || downloading ? <div className="debug-result-placeholder"><LoaderCircle size={18} className="spin" />{downloading ? '正在下载结果文档，请稍候…' : '正在生成调试结果文档，请稍候…'}</div>
      : result?.status === 'passed' ? <div className="debug-download">
        <FileText className="debug-document-icon" size={28} aria-hidden="true" />
        <div className="debug-document-info"><b>调试结果文档</b><p>{artifact?.name || (result.runId ? '生成已完成，结果文档尚未下载' : '结果文件未生成')}</p><p>{artifact ? `生成成功 · ${artifact.format || 'Markdown'}${current?.size !== undefined ? ` · ${Math.max(0.1, current.size / 1024).toFixed(1)} KB` : ''}${artifact.count !== undefined ? ` · ${artifact.count} 条结果` : ''} · ${result.origin === 'backend' ? '真实调试结果' : '前端模拟结果'}` : result.documentError || '请重新运行调试生成文档。'}</p>
          {result.runId && <p>运行编号：{result.runId}</p>}
          {current?.error && <p className="debug-document-error" role="alert">{current.error}</p>}
        </div>
        {current?.url && artifact ? <a className="button primary small" href={current.url} download={artifact.name}><Download size={14} />下载文档</a>
          : artifact && !current?.error ? <span className="helper-text">正在准备下载…</span> : onRetry ? <button type="button" className="button primary small" onClick={onRetry}>重试下载</button> : null}
      </div>
      : result?.status === 'failed' || result?.status === 'timeout' ? <p className="error-banner" role="alert">{result.status === 'timeout' ? '调试超时，未生成结果文档，请重新运行。' : '调试失败，未生成结果文档，请检查输入与挂载资源后重试。'}</p>
      : <p className="debug-result-placeholder">运行调试成功后，将在此处生成可下载的结果文档。</p>}
  </section>
}
