import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export default function Dialog({ title, children, footer, onClose, busy = false, wide = false, closeWhileBusy = false }: { title: ReactNode; children: ReactNode; footer?: ReactNode; onClose: () => void; busy?: boolean; wide?: boolean; closeWhileBusy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const dialog = ref.current
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog?.showModal()
    return () => { dialog?.close(); document.body.style.overflow = previousOverflow }
  }, [])
  return <dialog ref={ref} className={`developer-dialog ${wide ? 'wide' : ''}`} aria-labelledby={titleId} onCancel={event => { event.preventDefault(); if (!busy || closeWhileBusy) onClose() }}>
    <header className="dialog-header"><h2 id={titleId}>{title}</h2><button className="icon-button" aria-label="关闭弹窗" disabled={busy && !closeWhileBusy} onClick={onClose}><X size={18} /></button></header>
    <div className="dialog-body">{children}</div>
    {footer && <footer className="dialog-footer">{footer}</footer>}
  </dialog>
}
