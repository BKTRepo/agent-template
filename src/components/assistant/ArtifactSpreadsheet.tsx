import { useEffect, useState } from 'react'
import { getArtifactSheet } from '@/api/assistantArtifacts'
import Dialog from '@/components/developer/Dialog'
import type { CellEdit, EditableCellType, SheetArtifact, SheetCell, SheetPage } from '@/types/assistantArtifact'

const ROW_LIMIT = 25
const COLUMN_LIMIT = 12
const cellTypes: { id: EditableCellType; label: string }[] = [
  { id: 'text', label: '文本' }, { id: 'number', label: '数字' }, { id: 'boolean', label: '布尔值' },
  { id: 'formula', label: '公式' }, { id: 'blank', label: '清空单元格' },
]

export default function ArtifactSpreadsheet({ artifact, editing, changes, onChange }: {
  artifact: SheetArtifact; editing: boolean; changes: Partial<Record<string, CellEdit>>; onChange: (edit: CellEdit, original: SheetCell) => void
}) {
  const [index, setIndex] = useState(artifact.sheets[0]?.index ?? 0)
  const [offset, setOffset] = useState(0)
  const [columnOffset, setColumnOffset] = useState(0)
  const [page, setPage] = useState<SheetPage>()
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [cell, setCell] = useState<{ original: SheetCell; type: EditableCellType; value: string }>()
  const sheet = artifact.sheets.find(row => row.index === index)

  useEffect(() => {
    const controller = new AbortController()
    setPage(undefined)
    setError('')
    if (sheet) void getArtifactSheet(artifact, index, offset, columnOffset, controller.signal)
      .then(result => { if (!controller.signal.aborted) setPage(result) })
      .catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
    return () => controller.abort()
  }, [artifact, sheet, index, offset, columnOffset, retry])

  const invalid = cell?.type === 'number' && (!cell.value.trim() || !Number.isFinite(Number(cell.value))) ||
    cell?.type === 'formula' && (!cell.value.startsWith('=') || cell.value.length < 2)

  function confirmCell() {
    if (!cell || invalid) return
    const value = cell.type === 'blank' ? null : cell.type === 'boolean' ? cell.value === 'true' :
      cell.type === 'number' ? Number(cell.value) : cell.value
    onChange({ sheet_index: index, address: cell.original.address, type: cell.type, value }, cell.original)
    setCell(undefined)
  }

  if (!sheet) return <p className="empty-table">没有可预览的工作表</p>
  return <div className="artifact-sheet">
    <div className="artifact-sheet-controls">
      <label>工作表 <select aria-label="选择工作表" value={index} onChange={event => {
        setIndex(Number(event.target.value)); setOffset(0); setColumnOffset(0)
      }}>{artifact.sheets.map(row => <option key={row.index} value={row.index}>{row.name}</option>)}</select></label>
      <button className="button small" type="button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - ROW_LIMIT))}>上一组行</button>
      <button className="button small" type="button" disabled={offset + ROW_LIMIT >= Math.min(sheet.rows + 1, 1048576)} onClick={() => setOffset(offset + ROW_LIMIT)}>下一组行</button>
      <button className="button small" type="button" disabled={!columnOffset} onClick={() => setColumnOffset(Math.max(0, columnOffset - COLUMN_LIMIT))}>上一组列</button>
      <button className="button small" type="button" disabled={columnOffset + COLUMN_LIMIT >= Math.min(sheet.columns + 1, 16384)} onClick={() => setColumnOffset(columnOffset + COLUMN_LIMIT)}>下一组列</button>
      <span className="helper-text">{editing ? '点击单元格修改内容或数据类型。' : `${sheet.rows} 行 · ${sheet.columns} 列`}</span>
    </div>
    {error ? <div className="error-banner" role="alert">{error} <button className="button small" onClick={() => setRetry(value => value + 1)}>重试</button></div>
      : !page ? <p className="empty-table" role="status">正在读取工作表…</p>
        : <div className="artifact-sheet-scroll"><table aria-label={sheet.name}><thead><tr><th scope="col">#</th>{page.columns.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead>
          <tbody>{page.rows.map((row, rowIndex) => <tr key={rowIndex}><th scope="row">{page.offset + rowIndex + 1}</th>
            {row.map(original => {
              const draft = changes[`${index}:${original.address}`]
              const current = draft ?? original
              const content = current.value === null ? '' : String(current.value)
              return <td key={original.address} data-changed={!!draft} style={{ fontWeight: original.bold ? 'bold' : undefined }}>
                {editing && original.editable ? <button type="button" aria-label={`编辑单元格 ${original.address}`} onClick={() => setCell({
                  original, type: current.type === 'blank' || current.type === 'read_only' ? 'text' : current.type, value: content,
                })}>{content || ' '}</button> : content}
              </td>
            })}
          </tr>)}</tbody></table></div>}
    {cell && <Dialog title={`编辑单元格 ${cell.original.address}`} onClose={() => setCell(undefined)}
      footer={<><button className="button" onClick={() => setCell(undefined)}>取消</button>
        <button className="button primary" disabled={invalid} onClick={confirmCell}>确认单元格</button></>}>
      <div className="artifact-case-editor">
        <label>数据类型<select aria-label="单元格数据类型" value={cell.type} onChange={event => {
          const type = event.target.value as EditableCellType
          setCell({ ...cell, type, value: type === 'boolean' ? 'true' : cell.value })
        }}>{cellTypes.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        {cell.type === 'boolean' ? <label>单元格内容<select aria-label="单元格内容" value={cell.value} onChange={event => setCell({ ...cell, value: event.target.value })}>
          <option value="true">TRUE</option><option value="false">FALSE</option></select></label>
          : cell.type !== 'blank' && <label>单元格内容<textarea aria-label="单元格内容" value={cell.value}
            onChange={event => setCell({ ...cell, value: event.target.value })} /></label>}
        {invalid && <p className="platform-field-error">{cell.type === 'formula' ? '公式须以等号开头。' : '请输入有效数字。'}</p>}
      </div>
    </Dialog>}
  </div>
}
