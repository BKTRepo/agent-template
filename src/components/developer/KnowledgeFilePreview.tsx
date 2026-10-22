import { useEffect, useState } from 'react'
import Dialog from './Dialog'
import { canViewKnowledge } from '@/lib/access'
import { useAccessStore } from '@/stores/accessStore'
import { downloadBlob, readBlob } from '@/lib/resourceStorage'
import type { KnowledgeBase } from '@/types/developer'
export default function KnowledgeFilePreview({ kb, fileId, onClose }: { kb: KnowledgeBase; fileId: string; onClose: () => void }) {
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [blob, setBlob] = useState<Blob>()
  const [error, setError] = useState('')
  const file = kb.files.find(row => row.id === fileId)!
  useEffect(() => {
    let canceled = false, objectUrl = ''
    void (async () => {
      if (!canViewKnowledge(kb, useAccessStore.getState().actor)) throw new Error('没有此文件的查看权限。')
      const original = file.sampleContent !== undefined ? new Blob([file.sampleContent]) : await readBlob(`resource:${file.id}`)
      if (!original) throw new Error('原文件缺失，请重新上传。')
      if (canceled) return
      setBlob(original)
      if (/\.(txt|md|json|csv)$/i.test(file.name)) { const content = await original.slice(0, 512 * 1024).text(); if (!canceled) setText(content) }
      else if (/\.pdf$/i.test(file.name)) { objectUrl = URL.createObjectURL(new Blob([original], { type: 'application/pdf' })); setUrl(objectUrl) }
    })().catch(error => { if (!canceled) setError(error.message) })
    return () => { canceled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [kb, file])
  return <Dialog wide title={`文件预览 · ${file.name}`} onClose={onClose} footer={<><button className="button" onClick={onClose}>关闭</button><button className="button primary" disabled={!blob} onClick={() => blob && downloadBlob(blob, file.name)}>下载原文件</button></>}>
    {error ? <p className="error-banner" role="alert">{error}</p> : url ? <iframe className="document-preview" title={file.name} src={url} /> : text ? <><pre className="document-text">{text}</pre>{file.size > 512 * 1024 && <p className="helper-text">预览前512KB，下载可查看完整文件；上传不受此预览限制影响。</p>}</> : blob ? <p>该格式请下载原文件查看，在线转换预览需要后端预览服务支持。</p> : <p role="status">正在加载文件…</p>}
  </Dialog>
}
