import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { getKnowledgeUpdates, markKnowledgeUpdatesRead, type KnowledgeUpdate, type KnowledgeUpdates } from '@/api/knowledgeUpdates'
import { useAuthStore } from '@/stores/authStore'
import { useDeveloperStore } from '@/stores/developerStore'
import { useKnowledgeUpdatesStore } from '@/stores/knowledgeUpdatesStore'

const message = '该技能挂载的知识库已发布新版本，请同步更新'
const statuses = { processing: '处理中', completed: '已完成', failed: '失败' }
export default function KnowledgeUpdateBadge({ skillId, count = 0 }: { skillId: string; count?: number }) {
  const token = useAuthStore(state => state.session?.token)
  const summary = useKnowledgeUpdatesStore(state => state.summary)
  const currentCount = summary ? summary.skill_counts[skillId] ?? 0 : count
  const anchor = useRef<HTMLButtonElement>(null), panel = useRef<HTMLDivElement>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const [open, setOpen] = useState(false), [result, setResult] = useState<KnowledgeUpdates | null>(null)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  useEffect(() => { if (!currentCount) setOpen(false) }, [currentCount])
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setResult(null); setError('')
    void getKnowledgeUpdates(skillId, controller.signal).then(data => {
      if (!controller.signal.aborted && useAuthStore.getState().session?.token === token) setResult(data)
    }).catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
    const outside = (event: MouseEvent) => {
      if (!anchor.current?.contains(event.target as Node) && !panel.current?.contains(event.target as Node)) setOpen(false)
    }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); anchor.current?.focus() } }
    document.addEventListener('mousedown', outside); document.addEventListener('keydown', escape)
    return () => { controller.abort(); document.removeEventListener('mousedown', outside); document.removeEventListener('keydown', escape) }
  }, [open, skillId, token])
  useEffect(() => () => { if (closeTimer.current) clearTimeout(closeTimer.current) }, [])
  const show = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    const rect = anchor.current?.getBoundingClientRect()
    if (rect) setPosition({ top: Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - 320)), left: Math.max(8, Math.min(rect.left, window.innerWidth - Math.min(380, window.innerWidth - 24) - 12)) })
    setOpen(true)
  }
  const leave = () => { closeTimer.current = setTimeout(() => { if (!busy && !panel.current?.contains(document.activeElement)) setOpen(false) }, 220) }
  async function read(items: KnowledgeUpdate[]) {
    if (!token || busy || !items.length) return
    setBusy(true); setError('')
    try {
      let latest: Awaited<ReturnType<typeof markKnowledgeUpdatesRead>> | undefined
      for (let index = 0; index < items.length; index += 100) {
        if (useAuthStore.getState().session?.token !== token) return
        latest = await markKnowledgeUpdatesRead(skillId, items.slice(index, index + 100))
      }
      if (latest && useAuthStore.getState().session?.token === token) {
        setResult(latest)
        useDeveloperStore.getState().patch(skillId, { knowledgeUpdateCount: latest.knowledge_update_count })
        useKnowledgeUpdatesStore.getState().apply(latest.summary, token)
        if (!latest.items.length) setOpen(false)
      }
    } catch (reason) { if (useAuthStore.getState().session?.token === token) setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  if (!currentCount) return null
  return <><button ref={anchor} type="button" className="knowledge-update-badge" aria-label={message} title={message}
    aria-haspopup="dialog" aria-expanded={open} onMouseEnter={show} onMouseLeave={leave} onClick={show}>!</button>
    {open && createPortal(<div ref={panel} className="knowledge-update-popover" role="dialog" aria-label="知识库更新提醒" style={{ ...position, maxHeight: `calc(100dvh - ${position.top + 12}px)` }}
      onMouseEnter={() => { if (closeTimer.current) clearTimeout(closeTimer.current) }} onMouseLeave={leave}>
      <div className="knowledge-update-heading"><strong>知识库更新提醒</strong><button type="button" className="button small" onClick={() => setOpen(false)} aria-label="关闭知识库更新提醒">关闭</button></div>
      <p>{message}</p>{error && <p role="alert" className="platform-field-error">{error}</p>}
      {!result ? <p role="status">正在加载更新…</p> : <>
        <div className="knowledge-update-items">{result.items.map(item => <article key={item.notification_id}>
          <strong>挂载知识库「{item.knowledge_name}」已更新</strong>
          <p>{item.from_version} → {item.latest_version}</p>
          <p>最近变更摘要：{item.change_summary || '未填写变更摘要'}</p>
          <p>文档状态：{statuses[item.processing_status]}</p>
          <button type="button" className="button small" disabled={busy} onClick={() => void read([item])}>标记已读</button>
        </article>)}</div>
      </>}
    </div>, document.body)}</>
}
