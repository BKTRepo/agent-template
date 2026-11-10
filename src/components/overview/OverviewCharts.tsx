type TrendPoint = {
  start_date: string
  end_date: string
  artifact_count: number | null
  skill_call_count: number | null
}
export type TrendData = { bucket_days: 1 | 2 | 7; points: TrendPoint[] | null }
export type RankedSkill = { skill_id: number; name: string; call_count: number; artifact_count: number }
type QueryStatus = { loading: boolean; error?: string }

const bucketLabels = { 1: '按日', 2: '按双日', 7: '按周' }
const number = (value: number) => value.toLocaleString('zh-CN')
const axisStep = (max: number) => {
  const interval = Math.max(1, max / 4)
  const scale = 10 ** Math.floor(Math.log10(interval))
  return Math.ceil(interval / scale) * scale
}

function TrendChart({ points }: { points: TrendPoint[] }) {
  const width = Math.max(640, points.length * 38 + 120)
  const left = 62
  const right = width - 62
  const top = 16
  const bottom = 195
  const column = (right - left) / points.length
  const barWidth = Math.min(24, column * 0.56)
  const artifactStep = axisStep(points.reduce((max, point) => Math.max(max, point.artifact_count ?? 0), 0))
  const callStep = axisStep(points.reduce((max, point) => Math.max(max, point.skill_call_count ?? 0), 0))
  const hasArtifacts = points.some(point => point.artifact_count !== null)
  const hasCalls = points.some(point => point.skill_call_count !== null)
  const x = (index: number) => left + column * (index + 0.5)
  const y = (value: number, step: number) => bottom - (bottom - top) * value / (4 * step)
  const line = points.map((point, index) => point.skill_call_count === null ? '' :
    `${index > 0 && points[index - 1].skill_call_count !== null ? 'L' : 'M'}${x(index)},${y(point.skill_call_count, callStep)}`).join(' ')

  return <div className="overview-chart-scroll">
    <svg role="img" aria-label="蓝色柱形显示产出物数量，绿色折线显示 Skill 调用次数" viewBox={`0 0 ${width} 226`}
      style={{ minWidth: width }}>
      {[0, 1, 2, 3, 4].map(tick => {
        const position = y(tick, 1)
        return <g key={tick}>
          <line className="overview-chart-gridline" x1={left} y1={position} x2={right} y2={position} />
          {hasArtifacts && <text x={left - 8} y={position + 4} textAnchor="end">{number(tick * artifactStep)}</text>}
          {hasCalls && <text x={right + 8} y={position + 4}>{number(tick * callStep)}</text>}
        </g>
      })}
      {points.map((point, index) => point.artifact_count === null ? null :
        <rect key={point.start_date} className="overview-trend-bar" x={x(index) - barWidth / 2}
          y={y(point.artifact_count, artifactStep)} width={barWidth} height={bottom - y(point.artifact_count, artifactStep)} rx={3}>
          <title>{point.start_date} 至 {point.end_date} · 产出物 {number(point.artifact_count)}</title>
        </rect>)}
      <path className="overview-trend-line" d={line} />
      {points.map((point, index) => <g key={point.start_date}>
        {point.skill_call_count !== null && <circle className="overview-trend-dot" cx={x(index)} cy={y(point.skill_call_count, callStep)} r={3.5}>
          <title>{point.start_date} 至 {point.end_date} · 调用 {number(point.skill_call_count)}</title>
        </circle>}
        {(points.length <= 10 || index % Math.ceil(points.length / 10) === 0 || index === points.length - 1)
          && <text x={x(index)} y={215} textAnchor="middle">{point.start_date.slice(5)}</text>}
      </g>)}
    </svg>
  </div>
}

function emptyLabel(loading: boolean, error: string | undefined, empty: string) {
  if (loading) return '正在查询…'
  if (error) return '查询失败，可在期间指标处重试'
  return empty
}

export function OverviewTrend({ data, loading, error }: QueryStatus & { data?: TrendData }) {
  const points = data?.points
  return <section className="surface overview-analytic overview-analytic-trend">
    <div className="overview-analytic-header"><h2>产出物 &amp; 调用量趋势</h2>
      {data && <span>{bucketLabels[data.bucket_days]}</span>}
    </div>
    <div className="overview-chart-legend">
      <span><i className="overview-legend-bar" />产出物数量 · 左轴</span>
      <span><i className="overview-legend-line" />Skill 调用次数 · 右轴</span>
    </div>
    {points?.length ? <TrendChart points={points} /> :
      <div className="overview-chart-empty" role="status">{emptyLabel(loading, error, points == null ? '—' : '产出物 0 · Skill 调用 0')}</div>}
  </section>
}

export function OverviewRanking({ data, loading, error }: QueryStatus & { data?: RankedSkill[] | null }) {
  const rows = data?.slice(0, 5) ?? []
  const max = rows.reduce((value, row) => Math.max(value, row.call_count), 0)
  return <section className="surface overview-analytic">
    <div className="overview-analytic-header"><h2>热门技能 Top 5</h2><span>调用量</span></div>
    {rows.length > 0 ? <ol className="overview-ranking">
      {rows.map((row, index) => <li key={row.skill_id}>
        <span className="overview-rank-number">{String(index + 1).padStart(2, '0')}</span>
        <strong title={row.name}>{row.name}</strong>
        <div className="overview-rank-track" aria-hidden="true"><i style={{ width: `${max > 0 ? row.call_count / max * 100 : 0}%` }} /></div>
        <span>{number(row.call_count)}</span>
      </li>)}
    </ol> : <div className="overview-ranking-empty" role="status">{emptyLabel(loading, error, data == null ? '—' : '0 条记录')}</div>}
  </section>
}
