import { useRef } from 'react'
import { X } from 'lucide-react'

export default function ClearableSelect({ label, value, options, placeholder, onChange, disabled = false }: {
  label: string
  value: string
  options: { id: string; name: string }[]
  placeholder: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const select = useRef<HTMLSelectElement>(null)
  return <div className="clearable-select">
    <select ref={select} aria-label={label} className={!value ? 'select-placeholder' : undefined} value={value} disabled={disabled} onChange={event => onChange(event.target.value)}>
      <option value="">{placeholder}</option>
      {options.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
    </select>
    {value && !disabled && <button type="button" className="search-select-clear" aria-label={`清除${label}`} onMouseDown={event => event.preventDefault()} onClick={() => { onChange(''); select.current?.focus() }}><X size={14} aria-hidden="true" /></button>}
  </div>
}
