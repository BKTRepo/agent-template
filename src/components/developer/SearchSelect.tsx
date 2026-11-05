import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, Search, X } from 'lucide-react'

type Props = {
  label: string
  value: string
  options: { id: string; name: string }[]
  onChange: (id: string) => void
  disabled?: boolean
  placeholder?: string
  required?: boolean
}

export default function SearchSelect({ label, value, options, onChange, disabled = false, placeholder = '请选择', required = false }: Props) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [active, setActive] = useState(-1)
  const [position, setPosition] = useState<CSSProperties>({})
  const root = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const listId = useId()
  const selected = options.find(row => row.id === value)
  const keyword = search.trim().toLocaleLowerCase()
  const choices = options.filter(row => row.name.toLocaleLowerCase().includes(keyword))
  const expanded = open && !disabled

  function showOptions() {
    if (disabled) return
    setSearch('')
    setActive(options.findIndex(row => row.id === value))
    setOpen(true)
  }

  function choose(id: string) {
    onChange(id)
    setOpen(false)
    setSearch('')
  }

  useLayoutEffect(() => {
    if (!expanded) return
    function place(event?: Event) {
      if (!input.current || (event?.target instanceof Node && list.current?.contains(event.target))) return
      const rect = input.current.getBoundingClientRect()
      const boundary = root.current?.closest('dialog')?.getBoundingClientRect()
      const bottom = Math.min(window.innerHeight, boundary?.bottom ?? window.innerHeight) - 8
      const top = Math.max(0, boundary?.top ?? 0) + 8
      if (rect.bottom < top || rect.top > bottom) { setOpen(false); return }
      const below = bottom - rect.bottom - 6
      const above = rect.top - top - 6
      const upward = below < 220 && above > below
      setPosition({ left: rect.left, width: rect.width, maxHeight: Math.max(80, Math.min(280, upward ? above : below)), ...(upward ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }) })
    }
    place()
    document.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => { document.removeEventListener('scroll', place, true); window.removeEventListener('resize', place) }
  }, [expanded])

  useEffect(() => {
    if (!expanded) return
    function dismiss(event: Event) {
      if (event.target instanceof Node && (root.current?.contains(event.target) || list.current?.contains(event.target))) return
      setOpen(false)
    }
    document.addEventListener('pointerdown', dismiss)
    return () => {
      document.removeEventListener('pointerdown', dismiss)
    }
  }, [expanded])

  useEffect(() => {
    if (!expanded || active < 0 || !list.current) return
    const container = list.current
    const option = container.querySelector<HTMLElement>(`[data-index="${active}"]`)
    if (!option) return
    // Only scroll the option list; scrollIntoView can move the enclosing dialog
    // and dismiss this fixed-position menu during pointer selection.
    const top = option.offsetTop, bottom = top + option.offsetHeight
    if (top < container.scrollTop) container.scrollTop = top
    else if (bottom > container.scrollTop + container.clientHeight) container.scrollTop = bottom - container.clientHeight
  }, [expanded, active])

  return <div ref={root} className={`search-select${expanded ? ' is-open' : ''}`} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
  }}>
    <div className="search-select-control">
      <Search className="search-select-icon" size={16} aria-hidden="true" />
      <input ref={input} role="combobox" aria-label={label} aria-required={required} aria-autocomplete="list" aria-expanded={expanded} aria-controls={expanded ? listId : undefined} aria-activedescendant={expanded && active >= 0 && choices[active] ? `${listId}-${active}` : undefined} autoComplete="off" disabled={disabled} placeholder={expanded ? '输入关键词搜索' : placeholder} value={expanded ? search : selected?.name || value || ''}
        onFocus={showOptions} onClick={() => { if (!expanded) showOptions() }}
        onChange={event => { setSearch(event.target.value); setActive(-1); setOpen(true) }}
        onKeyDown={event => {
          if (event.nativeEvent.isComposing) return
          if (event.key === 'Escape' && expanded) { event.preventDefault(); event.stopPropagation(); setOpen(false) }
          else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            if (!expanded) showOptions()
            else if (choices.length) setActive(index => event.key === 'ArrowDown' ? (index + 1) % choices.length : (index <= 0 ? choices.length : index) - 1)
          } else if (event.key === 'Enter' && expanded) {
            event.preventDefault()
            if (choices[active]) choose(choices[active].id)
          } else if (event.key === 'Tab') setOpen(false)
        }} />
      <div className="search-select-actions">
        {value && !disabled && <button type="button" className="search-select-clear" aria-label={`清除${label}`} onMouseDown={event => event.preventDefault()} onClick={() => { choose(''); input.current?.focus(); setOpen(false) }}><X size={14} /></button>}
        <ChevronDown size={16} className="search-select-chevron" aria-hidden="true" />
      </div>
    </div>
    {expanded && createPortal(<div ref={list} id={listId} role="listbox" aria-label={`${label}选项`} className="search-select-options" style={position} onMouseDown={event => event.preventDefault()}>
      {choices.length ? choices.map((option, index) => <div key={option.id} id={`${listId}-${index}`} role="option" aria-selected={value === option.id} data-index={index} className={`search-select-option${index === active ? ' is-active' : ''}${option.id === value ? ' is-selected' : ''}`} onMouseEnter={() => setActive(index)} onClick={() => choose(option.id)}>
        <span>{option.name}</span>{option.id === value && <Check size={16} aria-hidden="true" />}
      </div>) : <div className="search-select-empty" role="status">未找到匹配项，请更换关键词</div>}
    </div>, root.current?.closest('dialog') || document.body)}
  </div>
}
