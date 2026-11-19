import type { ReactNode } from 'react'
import type { TestCase, TestCaseArtifact } from '@/types/assistantArtifact'

export type CaseView = 'map' | 'list' | 'sheet'

export function groupCases(cases: TestCase[], groups: TestCaseArtifact['groups']) {
  const byId = new Map(cases.map(item => [item.id, item]))
  const groupedIds = new Set<string>()
  const result = groups.map(({ title, caseIds }) => ({
    title, items: caseIds.flatMap(id => {
      const item = byId.get(id)
      if (!item || groupedIds.has(id)) return []
      groupedIds.add(id)
      return [item]
    }),
  })).filter(group => group.items.length)
  const ungrouped = cases.filter(item => !groupedIds.has(item.id))
  if (ungrouped.length) result.push({ title: '待归纳', items: ungrouped })
  return result.flatMap(group => {
    const sheets = new Map<number | null, TestCase[]>()
    for (const item of group.items) {
      const key = item.sheet_index ?? null
      const items = sheets.get(key) ?? []
      items.push(item)
      sheets.set(key, items)
    }
    return [...sheets.values()].map(items => ({ title: group.title, items }))
  })
}

export function CaseViewButtons({ view, onChange, hasSheets, sheetDisabled }: {
  view: CaseView; onChange: (view: CaseView) => void; hasSheets: boolean; sheetDisabled?: boolean
}) {
  return <div role="group" aria-label="测试案例视图">
    <button type="button" aria-pressed={view === 'map'} onClick={() => onChange('map')}>思维导图</button>
    <button type="button" aria-pressed={view === 'list'} onClick={() => onChange('list')}>用例</button>
    {hasSheets && <button type="button" disabled={sheetDisabled} aria-pressed={view === 'sheet'} onClick={() => onChange('sheet')}>原表</button>}
  </div>
}

export function CaseDetails({ item }: { item: TestCase }) {
  return <>
    {item.description && <p>{item.description}</p>}
    <dl><dt>前置条件</dt><dd>{item.preconditions || '—'}</dd></dl>
    <ol>{item.steps.map(step => <li key={step.id}>{step.action}
      {step.expected != null && <p>预期结果 · {step.expected || '—'}</p>}</li>)}</ol>
    {item.expected != null && <dl><dt>预期结果</dt><dd>{item.expected || '—'}</dd></dl>}
  </>
}

export function CaseList({ groups, actions }: {
  groups: ReturnType<typeof groupCases>; actions?: (item: TestCase) => ReactNode
}) {
  return <div className="artifact-case-list">{groups.map(({ title, items }) => <section key={items[0].id}>
    <h3>{items[0].sheet_name && `${items[0].sheet_name} · `}{title}</h3>
    {items.map(item => <article key={item.id}>
      <header><h4>{item.name}</h4>{actions?.(item)}</header>
      <CaseDetails item={item} />
    </article>)}
  </section>)}</div>
}
