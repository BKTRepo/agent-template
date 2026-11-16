import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { request } from '@/api/developerCenter'
import { downloadOverviewMetric, type OverviewMetric } from '@/api/overview'
import { OverviewTrend, OverviewRanking } from '@/components/overview/OverviewCharts'
import type { TrendData, RankedSkill } from '@/components/overview/OverviewCharts'

type Period = { start_date: string; end_date: string }
type LoadResult<T> = { path: string; attempt: number; data?: T; error?: string }
const cumulativeMetrics = [
  { key: 'connected_users', field: 'connected_user_count', title: '用户接入数量' },
  { key: 'online_skills', field: 'online_skill_count', title: '在册 Skill 总数' },
  { key: 'skill_calls', field: 'skill_call_count', title: '技能被调用次数' },
  { key: 'knowledge_mounts', field: 'knowledge_mount_count', title: '知识库被挂载次数' },
] satisfies Metric[]
const periodMetrics = [
  { key: 'active_users', field: 'active_user_count', title: '活跃用户数' },
  { key: 'test_artifacts', field: 'test_artifact_count', title: 'AI 辅助测试产出物' },
  { key: 'new_skills', field: 'new_skill_count', title: '新增技能数' },
  { key: 'new_knowledge_bases', field: 'new_knowledge_base_count', title: '新增知识库数' },
] satisfies Metric[]
type CountField = 'connected_user_count' | 'online_skill_count' | 'skill_call_count' | 'knowledge_mount_count'
  | 'active_user_count' | 'test_artifact_count' | 'new_skill_count' | 'new_knowledge_base_count'
type Metric = { key: OverviewMetric; field: CountField; title: string }
type Counts = Partial<Record<CountField, number | null>>
type PeriodSummary = Counts & { data_notes?: string[]; trend?: TrendData; top_skills?: RankedSkill[] | null }
const dateFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
})

function todayInShanghai() {
  const parts = dateFormatter.formatToParts(new Date())
  return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type)?.value).join('-')
}

function useOverviewQuery<T>(path: string) {
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<LoadResult<T>>()
  useEffect(() => {
    const controller = new AbortController()
    void request<T>(path, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setResult({ path, attempt, data })
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) {
        setResult({ path, attempt, error: reason instanceof Error ? reason.message : '查询失败，请重试。' })
      }
    })
    return () => controller.abort()
  }, [path, attempt])
  const current = result?.path === path && result.attempt === attempt ? result : undefined
  return { ...current, loading: !current, reload: () => setAttempt(value => value + 1) }
}

function MetricCard({ metric, count, loading, error, exporting, exportDisabled, onDetail }: {
  metric: Metric; count?: number | null; loading: boolean; error?: string; onDetail: () => void
  exporting: boolean; exportDisabled: boolean
}) {
  const fallback = metric.key === 'online_skills' || metric.key === 'new_skills' ? '0' : '—'
  return <article className="surface overview-metric">
    <div className="section-heading">
      <h3>{metric.title}</h3>
      <button className="button small" disabled={count == null || loading || !!error || exportDisabled} onClick={onDetail}
        aria-label={`下载${metric.title}明细Excel`}>{exporting ? '下载中…' : '明细'}</button>
    </div>
    <p className="overview-metric-value" aria-live="polite">{loading ? '加载中…' : error ? '—' : count?.toLocaleString('zh-CN') ?? fallback}</p>
  </article>
}

function MetricSection({ title, note, metrics, result, exporting, onDetail }: {
  title: string; note: string; metrics: Metric[]; result: ReturnType<typeof useOverviewQuery<Counts>>
  onDetail: (metric: Metric) => void
  exporting?: OverviewMetric
}) {
  return <section aria-label={title}>
    <div className="overview-section-heading"><h2>{title}</h2><span>{note}</span></div>
    {result.error && <div role="alert" className="overview-query-error">{result.error}
      <button className="button small" onClick={result.reload}>重试</button></div>}
    <div className="overview-metrics">
      {metrics.map(metric => <MetricCard key={metric.key} metric={metric} count={result.data?.[metric.field]}
        loading={result.loading} error={result.error} exporting={exporting === metric.key}
        exportDisabled={!!exporting} onDetail={() => onDetail(metric)} />)}
    </div>
  </section>
}

export default function OverviewPage() {
  const today = todayInShanghai()
  const [period, setPeriod] = useState<Period>(() => ({ start_date: `${today.slice(0, 7)}-01`, end_date: today }))
  const [draft, setDraft] = useState(period)
  const [dateError, setDateError] = useState('')
  const [exporting, setExporting] = useState<OverviewMetric>()
  const [exportError, setExportError] = useState('')
  const exportController = useRef<AbortController | null>(null)
  useEffect(() => () => exportController.current?.abort(), [])
  const cumulative = useOverviewQuery<Counts>('/overview/cumulative-summary')
  const selected = useOverviewQuery<PeriodSummary>(`/overview/period-summary?${new URLSearchParams(period)}`)

  async function downloadDetail(metric: Metric, selectedPeriod?: Period) {
    if (exportController.current) return
    const controller = new AbortController()
    exportController.current = controller
    setExporting(metric.key)
    setExportError('')
    const suffix = selectedPeriod ? `_${selectedPeriod.start_date}至${selectedPeriod.end_date}` : ''
    try {
      await downloadOverviewMetric(metric.key, `${metric.title}明细${suffix}.xlsx`, selectedPeriod, controller.signal)
    } catch (reason) {
      if (!controller.signal.aborted) setExportError(reason instanceof Error ? reason.message : '明细下载失败，请重试。')
    } finally {
      exportController.current = null
      setExporting(undefined)
    }
  }

  function query(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!draft.start_date || !draft.end_date) return setDateError('请选择开始日期和结束日期。')
    if (draft.start_date > draft.end_date) return setDateError('开始日期不能晚于结束日期。')
    if (draft.end_date > today || draft.start_date > today) return setDateError('不能选择未来日期。')
    setDateError('')
    if (draft.start_date === period.start_date && draft.end_date === period.end_date) selected.reload()
    else setPeriod(draft)
  }

  return <div className="overview-page">
    <form className="overview-date-filter" onSubmit={query} noValidate>
      <input aria-label="开始日期" type="date" className="input" value={draft.start_date} max={today} required
        onChange={event => { setDraft({ ...draft, start_date: event.target.value }); setDateError('') }} />
      <span aria-hidden="true" className="overview-date-separator">—</span>
      <input aria-label="结束日期" type="date" className="input" value={draft.end_date} max={today} required
        onChange={event => { setDraft({ ...draft, end_date: event.target.value }); setDateError('') }} />
      <button className="button primary" type="submit">查询</button>
      {dateError && <p role="alert" className="overview-date-error">{dateError}</p>}
    </form>
    {exportError && <p role="alert" className="overview-query-error">{exportError}</p>}
    <MetricSection title="累计指标" note="（不随期间变化）" metrics={cumulativeMetrics} result={cumulative} exporting={exporting}
      onDetail={metric => void downloadDetail(metric)} />
    <MetricSection title="期间指标" note={`${period.start_date} 至 ${period.end_date}`} metrics={periodMetrics} result={selected} exporting={exporting}
      onDetail={metric => void downloadDetail(metric, period)} />
    <div className="overview-analytics">
      <OverviewTrend data={selected.data?.trend} loading={selected.loading} error={selected.error} />
      <OverviewRanking data={selected.data?.top_skills} loading={selected.loading} error={selected.error} />
    </div>
  </div>
}
