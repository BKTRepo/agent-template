import { useEffect, useMemo, useState } from 'react'
import { getSheetPage, type PreviewMetadata, type SheetPage } from '@/api/knowledgePreview'

type SheetLoader = (sheet: number, offset: number, columnOffset: number, signal: AbortSignal) => Promise<SheetPage>

export default function SpreadsheetFileViewer({ kbId, metadata, zoom, loadPage }: {
  kbId?: string; metadata: Pick<PreviewMetadata, 'id' | 'generation' | 'sheets'>; zoom: number; loadPage?: SheetLoader
}) {
  const [sheet, setSheet] = useState(metadata.sheets[0]?.index ?? 0), [offset, setOffset] = useState(0), [columnOffset, setColumnOffset] = useState(0)
  const [data, setData] = useState<SheetPage>(), [error, setError] = useState(''), [loading, setLoading] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setData(undefined)
    const request = loadPage ? loadPage(sheet, offset, columnOffset, controller.signal)
      : getSheetPage(kbId!, String(metadata.id), metadata.generation, sheet, offset, columnOffset, controller.signal)
    void request
      .then(value => { if (!controller.signal.aborted) setData(value) })
      .catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [kbId, metadata.id, metadata.generation, sheet, offset, columnOffset, loadPage])
  const merges = useMemo(() => {
    const result = new Map<string, { hidden: boolean; rowSpan: number; colSpan: number }>()
    if (data) for (const [r1, c1, r2, c2] of data.merges) {
      const firstRow = Math.max(r1, offset + 1), firstColumn = Math.max(c1, columnOffset + 1)
      const lastRow = Math.min(r2, offset + data.rows.length), lastColumn = Math.min(c2, columnOffset + data.columns.length)
      for (let r = firstRow; r <= lastRow; r++) for (let c = firstColumn; c <= lastColumn; c++)
        result.set(`${r}:${c}`, { hidden: r !== firstRow || c !== firstColumn, rowSpan: lastRow - firstRow + 1, colSpan: lastColumn - firstColumn + 1 })
    }
    return result
  }, [data, offset, columnOffset])
  return <div className="spreadsheet-file-viewer">
    <div className="preview-sheet-tabs" role="tablist" aria-label="Excel工作表">{metadata.sheets.map(item => <button className={`button small ${item.index === sheet ? 'primary' : ''}`} role="tab" aria-selected={item.index === sheet} key={item.index} onClick={() => { setSheet(item.index); setOffset(0); setColumnOffset(0) }}>{item.name}</button>)}</div>
    {loading && <p role="status">正在加载工作表…</p>}{error && <p role="alert" className="error-banner">{error}</p>}
    {data && <><div className="spreadsheet-grid"><table style={{ fontSize: `${13 * zoom / 100}px` }}><caption className="sr-only">{data.name}</caption><thead><tr><th scope="col">行</th>{data.columns.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead>
      <tbody>{data.rows.map((row, ri) => <tr key={offset + ri}><th scope="row">{offset + ri + 1}</th>{row.map((cell, ci) => {
        const merge = merges.get(`${offset + ri + 1}:${columnOffset + ci + 1}`)
        return merge?.hidden ? null : <td key={ci} rowSpan={merge?.rowSpan} colSpan={merge?.colSpan} title={cell.formula ? '公式表达式' : undefined} style={{ fontWeight: cell.bold ? 700 : undefined, color: cell.color || undefined, background: cell.background || undefined, textAlign: cell.align }}>{cell.value === null ? '' : String(cell.value)}</td>
      })}</tr>)}</tbody></table>{!data.rows.length && <p className="helper-text">该区域无数据</p>}</div>
      <div className="preview-page-controls"><button className="button small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))}>上一页行</button><span>第 {offset + 1}–{Math.min(offset + 100, data.total_rows)} 行 / 共 {data.total_rows} 行</span><button className="button small" disabled={offset + 100 >= data.total_rows} onClick={() => setOffset(offset + 100)}>下一页行</button>
        <button className="button small" disabled={columnOffset === 0} onClick={() => setColumnOffset(Math.max(0, columnOffset - 50))}>前50列</button><span>共 {data.total_columns} 列</span><button className="button small" disabled={columnOffset + 50 >= data.total_columns} onClick={() => setColumnOffset(columnOffset + 50)}>后50列</button></div>
    </>}
  </div>
}
