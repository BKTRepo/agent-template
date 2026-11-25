export default function TestStageBadge({ name, code }: { name?: string | null; code?: string | null }) {
  return <span className={`test-stage-badge stage-${code || 'unassigned'}`}>{name || '阶段未配置'}</span>
}
