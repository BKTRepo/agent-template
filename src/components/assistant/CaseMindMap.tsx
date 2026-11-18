import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { FileText, GitFork, Minus, Plus } from 'lucide-react'
import type { TestCase } from '@/types/assistantArtifact'

interface Props {
  title: string
  groups: { title: string; items: TestCase[] }[]
  selectedId?: string
  disabled: boolean
  onSelect: (id: string) => void
  actions: (item: TestCase) => ReactNode
}

export default function CaseMindMap({ title, groups, selectedId, disabled, onSelect, actions }: Props) {
  const [zoom, setZoom] = useState(100)
  const [paths, setPaths] = useState<{ key: string; curve: string; color: number }[]>([])
  const graph = useRef<HTMLDivElement>(null)
  const sheets = useMemo(() => {
    const bySheet = new Map<string, { title: string; groups: Props['groups'] }>()
    for (const group of groups) {
      const itemsBySheet = new Map<string, TestCase[]>()
      for (const item of group.items) {
        const key = item.sheet_index == null ? 'legacy' : String(item.sheet_index)
        const items = itemsBySheet.get(key) ?? []
        items.push(item)
        itemsBySheet.set(key, items)
      }
      for (const [key, items] of itemsBySheet) {
        const sheet = bySheet.get(key) ?? { title: items[0].sheet_name || title, groups: [] }
        sheet.groups.push({ title: group.title, items })
        bySheet.set(key, sheet)
      }
    }
    return [...bySheet.entries()].sort(([a], [b]) => Number(a) - Number(b))
  }, [groups, title])

  useLayoutEffect(() => {
    const element = graph.current
    if (!element) return
    function redraw() {
      if (!element) return
      const bounds = element.getBoundingClientRect()
      const scale = zoom / 100
      const curves: typeof paths = []
      function link(from: Element, to: Element, key: string, color: number) {
        const a = from.getBoundingClientRect()
        const b = to.getBoundingClientRect()
        const x1 = (a.right - bounds.left) / scale, y1 = (a.top + a.height / 2 - bounds.top) / scale
        const x2 = (b.left - bounds.left) / scale, y2 = (b.top + b.height / 2 - bounds.top) / scale
        const middle = (x1 + x2) / 2
        curves.push({ key, color, curve: `M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}` })
      }
      element.querySelectorAll('.artifact-case-tree').forEach((tree, sheetIndex) => {
        const root = tree.querySelector('.artifact-case-root')
        if (!root) return
        tree.querySelectorAll('.artifact-case-branch').forEach((branch, index) => {
          const point = branch.querySelector('.artifact-case-point')
          if (!point) return
          link(root, point, `point-${sheetIndex}-${index}`, index % 4)
          branch.querySelectorAll('.artifact-case-leaf>button').forEach((leaf, leafIndex) =>
            link(point, leaf, `case-${sheetIndex}-${index}-${leafIndex}`, index % 4))
        })
      })
      setPaths(curves)
    }
    redraw()
    const observer = new ResizeObserver(redraw)
    observer.observe(element)
    element.querySelectorAll('.artifact-case-branch').forEach(branch => observer.observe(branch))
    return () => observer.disconnect()
  }, [sheets, zoom])

  return <div className="artifact-case-canvas">
    <div className="artifact-case-scroll" tabIndex={0} aria-label="测试案例思维导图画布">
      <div className="artifact-case-maps" ref={graph} style={{ zoom: zoom / 100 }}>
        <svg className="artifact-case-connections" aria-hidden="true">
          {paths.map(path => <path key={path.key} d={path.curve} data-palette={path.color} />)}
        </svg>
        {sheets.map(([sheetKey, sheet]) => <section className="artifact-case-tree" key={sheetKey} aria-label={`${sheet.title} 思维导图`}>
          <div className="artifact-case-root"><GitFork size={18} aria-hidden="true" /><strong>{sheet.title}</strong>
            <span>{sheet.groups.length} 个测试要点</span></div>
          <div className="artifact-case-branches">{sheet.groups.map(({ title: point, items }, index) =>
            <section className="artifact-case-branch" key={point} data-palette={index % 4}>
              <div className="artifact-case-point"><span>测试要点 <b>{String(index + 1).padStart(2, '0')}</b></span>
                <h3>{point}</h3><small>{items.length} 条用例</small></div>
              <div className="artifact-case-leaves">{items.map(item => <div className="artifact-case-leaf" key={item.id}>
                <button type="button" aria-expanded={item.id === selectedId} disabled={disabled}
                  onClick={() => onSelect(item.id)}><FileText size={16} aria-hidden="true" />{item.name}</button>
                {item.id === selectedId && actions(item)}
              </div>)}</div>
            </section>)}</div>
        </section>)}
      </div>
    </div>
    <div className="artifact-case-zoom" aria-label="导图缩放">
      <button type="button" aria-label="缩小导图" disabled={zoom <= 50} onClick={() => setZoom(value => value - 10)}><Minus size={16} /></button>
      <button type="button" aria-label="重置缩放" onClick={() => setZoom(100)}>{zoom}%</button>
      <button type="button" aria-label="放大导图" disabled={zoom >= 150} onClick={() => setZoom(value => value + 10)}><Plus size={16} /></button>
    </div>
  </div>
}
