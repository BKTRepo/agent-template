import type { ArtifactFile } from '@/types/assistantArtifact'

const timestamp = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})

export default function ArtifactTitle({ artifact }: { artifact: ArtifactFile }) {
  const date = artifact.createdAt ? new Date(artifact.createdAt) : undefined
  return <span className="artifact-case-title">测试产出物
    <small><strong>{artifact.name}.{artifact.fileType}</strong>
      {date && Number.isFinite(date.getTime()) && <> · <time dateTime={artifact.createdAt}>{timestamp.format(date)}</time></>}
    </small>
  </span>
}
