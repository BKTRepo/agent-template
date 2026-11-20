import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { formatSkillClassDescription } from '@/lib/descriptionPreview'

export default function SkillClassDescription({ description }: { description: string }) {
  const text = formatSkillClassDescription(description)
  const id = useId()
  const target = useRef<HTMLParagraphElement>(null)
  const closeTimer = useRef<number>(undefined)
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<CSSProperties>()

  function showFullDescription() {
    window.clearTimeout(closeTimer.current)
    const element = target.current
    if (element && element.scrollHeight > element.clientHeight + 1) setOpen(true)
  }

  function dismissSoon() {
    window.clearTimeout(closeTimer.current)
    closeTimer.current = window.setTimeout(() => setOpen(false), 180)
  }

  useEffect(() => () => window.clearTimeout(closeTimer.current), [])
  useLayoutEffect(() => {
    if (!open) return
    function place() {
      const rect = target.current?.getBoundingClientRect()
      if (!rect || rect.bottom <= 0 || rect.top >= window.innerHeight) {
        setOpen(false)
        return
      }
      const below = window.innerHeight - rect.bottom
      const above = rect.top
      const upward = below < 180 && above > below
      setPosition({
        left: rect.left, width: rect.width,
        maxHeight: Math.min(340, Math.max(48, (upward ? above : below) - 16)),
        ...(upward ? { bottom: window.innerHeight - rect.top + 8 } : { top: rect.bottom + 8 }),
      })
    }
    place()
    window.addEventListener('resize', place)
    document.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      document.removeEventListener('scroll', place, true)
    }
  }, [open])

  if (!text.trim()) return null
  return <>
    <p ref={target} className="skill-class-summary" tabIndex={0} aria-describedby={open ? id : undefined}
      onMouseEnter={showFullDescription} onMouseLeave={dismissSoon} onFocus={showFullDescription}
      onBlur={dismissSoon} onKeyDown={event => { if (event.key === 'Escape') setOpen(false) }}>
      {text}
    </p>
    {open && position && createPortal(<div id={id} role="tooltip" className="skill-class-tooltip" style={position}
      onMouseEnter={showFullDescription} onMouseLeave={dismissSoon}>{text}</div>, document.body)}
  </>
}
