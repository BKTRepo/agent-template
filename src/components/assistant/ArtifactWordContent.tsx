import { useState, type ReactNode } from 'react'
import type { WordBlock } from '@/types/assistantArtifact'

interface Props {
  blocks: WordBlock[]
  changes: Record<string, string>
  editing: boolean
  onChange: (id: string, before: string, text: string) => void
}

export default function ArtifactWordContent({ blocks, changes, editing, onChange }: Props) {
  const [active, setActive] = useState('')

  function render(items: WordBlock[], prefix = 'block'): ReactNode {
    return items.map((block, index) => {
      const key = `${prefix}-${index}`
      if (block.type === 'table') return <table key={key}><tbody>{block.rows.map((row, rowIndex) =>
        <tr key={rowIndex}>{row.map((cell, columnIndex) => <td key={columnIndex}>{render(cell, `${key}-${rowIndex}-${columnIndex}`)}</td>)}</tr>)}</tbody></table>
      const text = changes[block.id] ?? block.text
      const content = text !== block.text || !block.runs.length ? text : block.runs.map((run, runIndex) =>
        <span key={runIndex} style={{ fontWeight: run.bold ? 'bold' : undefined, fontStyle: run.italic ? 'italic' : undefined,
          textDecoration: run.underline ? 'underline' : undefined }}>{run.text}</span>)
      if (editing && block.editable) {
        if (active === key) return <div className="artifact-word-edit" key={key}>
          <textarea aria-label={`编辑段落 ${block.id}`} autoFocus value={text}
            onChange={event => onChange(block.id, block.text, event.target.value)} />
          <button className="button small" type="button" onClick={() => setActive('')}>完成段落编辑</button>
        </div>
        return <button key={key} type="button" className="artifact-word-paragraph editable" data-heading={block.heading}
          aria-label={`编辑段落：${text || '空段落'}`} onClick={() => setActive(key)}>{content || '空段落'}</button>
      }
      return <div key={key} className="artifact-word-paragraph" data-heading={block.heading}>
        {content}{editing && !block.editable && <small> · 复杂段落，只读</small>}
      </div>
    })
  }

  return <div className="artifact-word-paper">{render(blocks)}</div>
}
