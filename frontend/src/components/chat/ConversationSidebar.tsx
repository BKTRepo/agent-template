import { useEffect, useRef, useState } from 'react'
import {
  Plus, Trash2, MessageSquare, Loader2, Search,
  MoreHorizontal, Pin, PinOff, Pencil, Settings2,
} from 'lucide-react'
import { Dropdown, DropdownTrigger, DropdownPopover, DropdownMenu, DropdownItem, buttonVariants } from '@heroui/react'
import { toast } from '@/lib/toast'
import { DeleteConversationDialog } from '@/components/chat/DeleteConversationDialog'
import { ConversationSearchDialog } from '@/components/chat/ConversationSearchDialog'
import { useConversationStore } from '@/stores/conversationStore'
import type { Conversation } from '@/types/api'
import { cn } from '@/lib/utils'

/** 侧栏菜单项通用样式（图标 + 标签） */
function itemClass(active = false): string {
  return cn(
    'group flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors',
    active
      ? 'bg-accent-soft font-medium text-accent-soft-foreground'
      : 'text-foreground hover:bg-default',
  )
}

export function ConversationSidebar({ onOpenSettings }: { onOpenSettings?: () => void }) {
  const [renamingId, setRenamingId] = useState<number | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const editingRef = useRef<number | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null)
  /** 当前展开操作菜单的会话: 菜单打开期间强制显示 ... 按钮,
      避免弹出层遮住行触发 group-hover 失效、按钮 display 切换导致弹层锚点错位 */
  const [menuOpenId, setMenuOpenId] = useState<number | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)

  // Ctrl+K / Cmd+K 打开会话搜索弹窗
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const conversations = useConversationStore.use.conversations()
  const currentId = useConversationStore.use.currentId()
  const startNew = useConversationStore.use.startNew()
  const selectConversation = useConversationStore.use.selectConversation()
  const removeConversation = useConversationStore.use.removeConversation()
  const rename = useConversationStore.use.rename()
  const setPinned = useConversationStore.use.setPinned()

  const pinned = conversations.filter((c) => c.pinned)
  const recent = conversations.filter((c) => !c.pinned)

  const startRename = (c: Conversation) => {
    editingRef.current = c.id
    setRenameValue(c.title)
    setRenamingId(c.id)
  }

  const commitRename = async (conv: Conversation) => {
    if (editingRef.current !== conv.id) return
    editingRef.current = null
    const next = renameValue.trim()
    setRenamingId(null)
    if (next && next !== conv.title) {
      try {
        await rename(conv.id, next)
      } catch {
        toast.danger('重命名失败')
      }
    }
  }

  const cancelRename = () => {
    editingRef.current = null
    setRenamingId(null)
  }

  const handleConfirmDelete = async () => {
    const target = deleteTarget
    setDeleteTarget(null)
    if (!target) return
    try {
      await removeConversation(target.id)
    } catch {
      toast.danger('删除失败')
    }
  }

  const handleMenuAction = async (key: string | number, c: Conversation) => {
    if (key === 'pin') {
      try {
        await setPinned(c.id, !c.pinned)
      } catch {
        toast.danger('置顶操作失败')
      }
    } else if (key === 'rename') {
      startRename(c)
    } else if (key === 'delete') {
      setDeleteTarget(c)
    }
  }

  const renderRow = (c: Conversation) => {
    const menuOpen = menuOpenId === c.id
    return (
    <div
      key={c.id}
      onClick={() => {
        if (renamingId !== c.id) selectConversation(c.id)
      }}
      className={itemClass(c.id === currentId)}
    >
      {c.generating ? (
        <Loader2 className="size-4 shrink-0 animate-spin text-accent" />
      ) : (
        <MessageSquare className="size-4 shrink-0 opacity-70" />
      )}

      {renamingId === c.id ? (
        <input
          autoFocus
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          onFocus={(e) => e.currentTarget.select()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commitRename(c)
            } else if (e.key === 'Escape') cancelRename()
          }}
          onBlur={() => commitRename(c)}
          className="min-w-0 flex-1 border-b border-accent bg-transparent py-px text-sm leading-tight outline-none"
        />
      ) : (
        <span className="min-w-0 flex-1 truncate" title={c.title}>{c.title}</span>
      )}

      {/* 置顶会话: 默认常驻显示图钉按钮, 悬停行或菜单打开时切换为 ... 操作按钮 */}
      {c.pinned && renamingId !== c.id && (
        <span
          className={cn(
            'flex size-6 shrink-0 items-center justify-center',
            menuOpen ? 'hidden' : 'group-hover:hidden',
          )}
          aria-label="已置顶"
        >
          <Pin className="size-3.5 text-accent" />
        </span>
      )}

      <span onClick={(e) => e.stopPropagation()}>
        <Dropdown onOpenChange={(open) => setMenuOpenId(open ? c.id : null)}>
          {/* DropdownTrigger 自身即 RAC <button>, 内部不可再嵌 Button（button 套 button
              为非法 HTML）; 用 buttonVariants 直接为 trigger 应用按钮样式。
              inline-flex 等工具类用于压过 dropdown__trigger 的 display:inline-block。 */}
          <DropdownTrigger
            aria-label="更多操作"
            className={cn(
              buttonVariants({ variant: 'ghost', size: 'sm', isIconOnly: true }),
              'inline-flex size-6 shrink-0 items-center justify-center transition-opacity group-focus-within:opacity-100 data-[pressed]:opacity-100',
              c.pinned
                ? menuOpen
                  ? 'inline-flex'
                  : 'hidden group-hover:inline-flex'
                : 'opacity-0 group-hover:opacity-100',
            )}
          >
            <MoreHorizontal className="size-3.5" />
          </DropdownTrigger>
          <DropdownPopover placement="bottom end">
            <DropdownMenu onAction={(key) => handleMenuAction(key as string, c)} aria-label="会话操作">
              <DropdownItem id="pin">
                {c.pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />}
                {c.pinned ? '取消置顶' : '置顶'}
              </DropdownItem>
              <DropdownItem id="rename">
                <Pencil className="size-4" /> 重命名
              </DropdownItem>
              <DropdownItem id="delete" className="text-danger" textValue="删除">
                <Trash2 className="size-4" /> 删除
              </DropdownItem>
            </DropdownMenu>
          </DropdownPopover>
        </Dropdown>
      </span>
    </div>
    )
  }

  return (
    <div className="flex h-full w-[240px] shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-surface p-2 py-3">
      {/* 会话搜索入口（按钮样式, 点击或 Ctrl+K 打开搜索弹窗） */}
      <button
        type="button"
        onClick={() => setSearchOpen(true)}
        aria-label="搜索对话"
        className="mb-1 flex w-full items-center gap-2 rounded-lg border border-border/70 bg-default/40 px-2.5 py-1.5 text-xs text-muted transition-colors hover:bg-default/70 hover:text-foreground"
      >
        <Search className="size-3.5 shrink-0" />
        <span className="flex-1 text-left">搜索对话</span>
        <kbd className="rounded border border-border px-1 py-px font-mono text-[10px] text-muted/70">Ctrl K</kbd>
      </button>

      {/* 主操作菜单 */}
      <div className="flex flex-col gap-0.5">
        <button type="button" onClick={startNew} className={itemClass()}>
          <Plus className="size-4 shrink-0 opacity-70" />
          <span className="flex-1 text-left">新建对话</span>
        </button>
        {onOpenSettings && (
          <button type="button" onClick={onOpenSettings} className={itemClass()}>
            <Settings2 className="size-4 shrink-0 opacity-70" />
            <span className="flex-1 text-left">参数设置</span>
          </button>
        )}
      </div>

      <div className="mx-2.5 my-2 h-px shrink-0 bg-border/60" />

      {/* 历史对话 */}
      <div className="shrink-0 px-2.5 pb-2 pt-1 text-xs font-normal tracking-wider text-muted">
        历史对话
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {conversations.length === 0 ? (
          <div className="px-2.5 py-6 text-center text-xs text-foreground">暂无对话，点击上方新建</div>
        ) : (
          <div className="flex flex-col gap-0.5 pb-1">
            {pinned.length > 0 && (
              <>
                <div className="px-2.5 pb-0.5 pt-1 text-[10px] font-medium text-foreground">
                  置顶
                </div>
                {pinned.map(renderRow)}
              </>
            )}
            {recent.length > 0 && (
              <>
                {pinned.length > 0 && (
                  <div className="px-2.5 pb-0.5 pt-1.5 text-[10px] font-medium text-foreground">最近</div>
                )}
                {recent.map(renderRow)}
              </>
            )}
          </div>
        )}
      </div>

      <DeleteConversationDialog
        conversation={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleConfirmDelete}
      />

      <ConversationSearchDialog open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  )
}
