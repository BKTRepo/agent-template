import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { request } from '@/api/developerCenter'
import ListPagination from '@/components/common/ListPagination'
import Dialog from '@/components/developer/Dialog'
import { OverviewTrend, OverviewRanking } from '@/components/overview/OverviewCharts'
import type { TrendData, RankedSkill } from '@/components/overview/OverviewCharts'

type Period = { start_date: string; end_date: string }
type DetailValue = string | number | null
type MetricPage = { items: Record<string, DetailValue>[]; total: number; page: number; page_size: number; pages: number }
type LoadResult<T> = { path: string; attempt: number; data?: T; error?: string }
type Column = [key: string, title: string, kind?: 'time' | 'status' | 'duration']

const skillIdentity: Column[] = [['name', 'Skill 名称'], ['skill_class_name', '所属技能大类'], ['application_name', '所属应用']]
const skillState: Column[] = [['version', '线上版本号'], ['status', '当前状态', 'status']]
const userIdentity: Column[] = [['department', '部门'], ['username', '用户名'], ['employee_no', '用户工号']]
const cumulativeMetrics = [
  { key: 'connected_users', field: 'connected_user_count', title: '用户接入数量',
    columns: [...userIdentity, ['first_access_at', '首次接入时间', 'time'], ['last_login_at', '最近登录时间', 'time'], ['login_count', '累计登录次数']] },
  { key: 'online_skills', field: 'online_skill_count', title: '在册 Skill 总数',
    columns: [...skillIdentity, ['published_at', '上线时间', 'time'], ...skillState, ['call_count', '累计调用次数'], ['last_called_at', '最近调用时间', 'time']] },
  { key: 'skill_calls', field: 'skill_call_count', title: '技能被调用次数',
    columns: [['skill_name', 'Skill 名称'], ['operator_login_name', '操作人工号'], ['called_at', '调用时间', 'time']] },
  { key: 'knowledge_mounts', field: 'knowledge_mount_count', title: '知识库被挂载次数',
    columns: [['knowledge_base_name', '知识库名称'], ['knowledge_base_version', '知识库版本'], ['target_name', '挂载目标名称'], ['operator_login_name', '操作人工号'], ['mounted_at', '挂载时间', 'time']] },
] satisfies Metric[]
const periodMetrics = [
  { key: 'active_users', field: 'active_user_count', title: '活跃用户数',
    columns: [...userIdentity, ['conversation_call_count', '智能对话调用次数'], ['first_called_at', '首次调用时间', 'time'], ['last_called_at', '近期调用时间', 'time']] },
  { key: 'test_artifacts', field: 'test_artifact_count', title: 'AI 辅助测试产出物',
    columns: [['generated_at', '产出时间', 'time'], ['employee_no', '用户工号'], ['department', '所属部门'], ['artifact_type', '产出物类型'], ['skill_name', 'Skill 名称'], ['artifact_count', '产出物数量'], ['duration_ms', '生成耗时', 'duration'], ['status', '生成状态']] },
  { key: 'new_skills', field: 'new_skill_count', title: '新增技能数',
    columns: [...skillIdentity, ['created_time', '创建时间', 'time'], ['creator_login_name', '创建人工号'], ...skillState] },
  { key: 'new_knowledge_bases', field: 'new_knowledge_base_count', title: '新增知识库数',
    columns: [['name', '知识库名称'], ['application_name', '所属应用'], ['creator_login_name', '创建人工号'], ['created_time', '创建时间', 'time'], ['version', '当前版本号'], ['file_count', '文件数量'], ['updated_at', '最近维护时间', 'time']] },
] satisfies Metric[]
type CountField = 'connected_user_count' | 'online_skill_count' | 'skill_call_count' | 'knowledge_mount_count'
  | 'active_user_count' | 'test_artifact_count' | 'new_skill_count' | 'new_knowledge_base_count'
type Metric = { key: string; field: CountField; title: string; columns: Column[] }
type Counts = Partial<Record<CountField, number | null>>
type PeriodSummary = Counts & { trend?: TrendData; top_skills?: RankedSkill[] | null }
const dateFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
})
const timeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})

function todayInShanghai() {
  const parts = dateFormatter.formatToParts(new Date())
  return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type)?.value).join('-')
}

function displayTime(value: string | null) {
  if (!value) return '—'
  const timestamp = new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}+08:00`)
  return Number.isNaN(timestamp.getTime()) ? '—' : timeFormatter.format(timestamp)
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

function MetricCard({ metric, count, loading, error, onDetail }: {
  metric: Metric; count?: number | null; loading: boolean; error?: string; onDetail: () => void
}) {
  const fallback = metric.key === 'online_skills' || metric.key === 'new_skills' ? '0' : '—'
  return <article className="surface overview-metric">
    <div className="section-heading">
      <h3>{metric.title}</h3>
      <button className="button small" disabled={count == null || loading || !!error} onClick={onDetail}
        aria-label={`查看${metric.title}明细`}>明细</button>
    </div>
    <p className="overview-metric-value" aria-live="polite">{loading ? '加载中…' : error ? '—' : count?.toLocaleString('zh-CN') ?? fallback}</p>
  </article>
}

function MetricDetails({ metric, period, onClose }: { metric: Metric; period?: Period; onClose: () => void }) {
  const [page, setPage] = useState(1)
  const params = new URLSearchParams({ metric: metric.key, page: String(page), page_size: '20', ...period })
  const { data, error, loading, reload } = useOverviewQuery<MetricPage>(`/overview/metric-detail?${params}`)
  return <Dialog wide title={`${metric.title}明细`} onClose={onClose}>
    {period && <p className="helper-text">{period.start_date} 至 {period.end_date}</p>}
    {loading && <p role="status">正在查询明细…</p>}
    {error && <div role="alert"><p>{error}</p><button className="button small" onClick={reload}>重试</button></div>}
    {data && <>
      <div className="implementation-table-wrap">
        <table className="implementation-table">
          <thead><tr>{metric.columns.map(([key, title]) => <th key={key} scope="col">{title}</th>)}</tr></thead>
          <tbody>{data.items.map((row, index) => <tr key={row.id ?? row.skill_id ?? index}>
            {metric.columns.map(([key, , kind]) => <td key={key}>
              {kind === 'time' ? displayTime(typeof row[key] === 'string' ? row[key] : null)
                : kind === 'status' && row[key] === 'ONLINE' ? <span className="status-tag green">已上线</span>
                : kind === 'duration' && row[key] != null ? `${row[key]} ms`
                : (row[key] ?? '—') === '' ? '—' : row[key] ?? '—'}
            </td>)}
          </tr>)}
          {!data.items.length && <tr><td className="empty-table" colSpan={metric.columns.length}>暂无符合条件的记录</td></tr>}</tbody>
        </table>
      </div>
      <ListPagination total={data.total} page={data.page} pages={data.pages} pageSize={data.page_size}
        label="技能明细分页" onPageChange={setPage} />
    </>}
  </Dialog>
}

function MetricSection({ title, note, metrics, result, onDetail }: {
  title: string; note: string; metrics: Metric[]; result: ReturnType<typeof useOverviewQuery<Counts>>
  onDetail: (metric: Metric) => void
}) {
  return <section aria-label={title}>
    <div className="overview-section-heading"><h2>{title}</h2><span>{note}</span></div>
    {result.error && <div role="alert" className="overview-query-error">{result.error}
      <button className="button small" onClick={result.reload}>重试</button></div>}
    <div className="overview-metrics">
      {metrics.map(metric => <MetricCard key={metric.key} metric={metric} count={result.data?.[metric.field]}
        loading={result.loading} error={result.error} onDetail={() => onDetail(metric)} />)}
    </div>
  </section>
}

export default function OverviewPage() {
  const today = todayInShanghai()
  const [period, setPeriod] = useState<Period>(() => ({ start_date: `${today.slice(0, 7)}-01`, end_date: today }))
  const [draft, setDraft] = useState(period)
  const [dateError, setDateError] = useState('')
  const [detail, setDetail] = useState<{ metric: Metric; period?: Period }>()
  const cumulative = useOverviewQuery<Counts>('/overview/cumulative-summary')
  const selected = useOverviewQuery<PeriodSummary>(`/overview/period-summary?${new URLSearchParams(period)}`)

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
    <MetricSection title="累计指标" note="（不随期间变化）" metrics={cumulativeMetrics} result={cumulative}
      onDetail={metric => setDetail({ metric })} />
    <MetricSection title="期间指标" note={`${period.start_date} 至 ${period.end_date}`} metrics={periodMetrics} result={selected}
      onDetail={metric => setDetail({ metric, period })} />
    <div className="overview-analytics">
      <OverviewTrend data={selected.data?.trend} loading={selected.loading} error={selected.error} />
      <OverviewRanking data={selected.data?.top_skills} loading={selected.loading} error={selected.error} />
    </div>
    {detail && <MetricDetails {...detail} onClose={() => setDetail(undefined)} />}
  </div>
}
