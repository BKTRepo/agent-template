import { useEffect, useState } from 'react'
import { ChevronLeft, Pencil, Plus, Search, Star, Trash2 } from 'lucide-react'
import Dialog from '@/components/developer/Dialog'
import { listChatConversations, renameChatConversation, type ChatConversation } from '@/api/assistant'

export default function AssistantSessions({ sessions, activeId, onClose, onSelect, onNew, onFavorite, onDelete, onClearAll, onRenamed }: {
  sessions: ChatConversation[]; activeId: string; onClose: () => void; onSelect: (id: string) => void; onNew: () => void
  onFavorite: (item: ChatConversation) => void; onDelete: (id: string) => Promise<void>; onClearAll: () => Promise<void>; onRenamed: (item: ChatConversation) => void
}) {
  const [keyword, setKeyword] = useState(''), [favoriteOnly, setFavoriteOnly] = useState(false), [found, setFound] = useState<ChatConversation[]>()
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [renaming, setRenaming] = useState<ChatConversation>(), [title, setTitle] = useState('')
  const [deleting, setDeleting] = useState<string>()
  useEffect(() => {
    let current = true
    if (!keyword.trim()) { setFound(undefined); return }
    const timer = window.setTimeout(() => {
      void listChatConversations(keyword.trim(), favoriteOnly ? true : undefined).then(result => { if (current) setFound(result.items) })
        .catch(reason => { if (current) setError((reason as Error).message) })
    }, 250)
    return () => { current = false; window.clearTimeout(timer) }
  }, [keyword, favoriteOnly, sessions])
  const rows = (found ?? sessions).filter(item => !favoriteOnly || item.favorite).slice().sort((left, right) => {
    const leftTime = Date.parse(left.updatedAt) || 0
    const rightTime = Date.parse(right.updatedAt) || 0
    return rightTime - leftTime
  })
  async function confirm() {
    setBusy(true); setError('')
    try { if (deleting === 'all') await onClearAll(); else if (deleting) await onDelete(deleting); setDeleting(undefined) }
    catch (reason) { setError((reason as Error).message) } finally { setBusy(false) }
  }
  function saveRename() {
    if (!renaming || busy || !title.trim()) return
    setBusy(true)
    void renameChatConversation(renaming.id, title.trim()).then(item => { onRenamed(item); setRenaming(undefined) }).catch(reason => setError((reason as Error).message)).finally(() => setBusy(false))
  }
  return <aside className="aip-session-drawer" aria-label="会话列表">
    <header><button aria-label="返回对话" onClick={onClose}><ChevronLeft size={18} /></button><b>会话记录</b><button className="aip-new-session" onClick={onNew}><Plus size={14} />新建</button></header>
    <section className="aip-session-tools"><label className="aip-session-search"><Search size={15} aria-hidden="true" /><input aria-label="搜索历史会话" placeholder="搜索会话标题或内容" value={keyword} onChange={event => { setKeyword(event.target.value); setFound(undefined) }} /></label>
      <div className="aip-session-tabs"><button className="aip-action" aria-pressed={!favoriteOnly} onClick={() => setFavoriteOnly(false)}>全部</button><button className="aip-action" aria-pressed={favoriteOnly} onClick={() => setFavoriteOnly(true)}>收藏</button></div></section>
    {error && <p role="alert" className="aip-error">{error}</p>}
    <div>{rows.map(session => <article key={session.id} className={session.id === activeId ? 'active' : ''}>
      <button className={session.favorite ? 'favorite' : ''} aria-label={session.favorite ? '取消收藏' : '收藏会话'} onClick={() => onFavorite(session)}><Star size={13} /></button>
      <div><button className="aip-session-select" onClick={() => onSelect(session.id)}><b>{session.title}</b><p>{new Date(session.updatedAt).toLocaleString('zh-CN')}</p></button>
        <button className="aip-session-rename" aria-label={`重命名 ${session.title}`} onClick={() => { setRenaming(session); setTitle(session.title) }}><Pencil size={11} />重命名</button></div>
      {!!session.unreadCount && <i>{session.unreadCount}</i>}
      <button className="delete" aria-label={`删除会话 ${session.title}`} onClick={() => setDeleting(session.id)}><Trash2 size={13} /></button>
    </article>)}{!rows.length && <p className="empty-table">暂无匹配会话</p>}</div>
    <button className="aip-action danger" onClick={() => setDeleting('all')}>清空全部会话</button>
    {renaming && <Dialog className="assistant-owned-dialog aip-rename-dialog" title="重命名会话" busy={busy} onClose={() => setRenaming(undefined)} footer={<>
      <button className="button" disabled={busy} onClick={() => setRenaming(undefined)}>取消</button><button className="button primary" disabled={busy || !title.trim()} onClick={saveRename}>保存</button></>}><div className="aip-rename-form"><label htmlFor="assistant-session-title">会话名称</label><input id="assistant-session-title" autoFocus aria-label="会话名称" maxLength={255} value={title} onChange={event => setTitle(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); saveRename() } }} /><p>修改后会同步到会话记录，最多 255 个字符。</p></div></Dialog>}
    {deleting && <Dialog className="assistant-owned-dialog" title={deleting === 'all' ? '清空全部会话' : '删除会话'} busy={busy} onClose={() => setDeleting(undefined)} footer={<>
      <button className="button" disabled={busy} onClick={() => setDeleting(undefined)}>取消</button><button className="button primary" disabled={busy} onClick={() => void confirm()}>确认删除</button></>}>
      <p>{deleting === 'all' ? '将删除全部会话及临时产出物，正式资产不受影响。是否继续？' : '将删除此会话及临时产出物，删除后不可恢复；已纳入的正式资产不受影响。'}</p></Dialog>}
  </aside>
}
