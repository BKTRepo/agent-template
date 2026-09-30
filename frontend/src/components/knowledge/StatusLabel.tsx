import { memo } from 'react'
import type { DocumentStatus } from '@/types/api'

/**
 * 文档状态徽标。HeroUI Chip 仅提供 5 种语义色，无法覆盖流水线各阶段的专属配色，
 * 故沿用原前端的分阶段配色方案（Tailwind 默认调色板, 本地打包）。
 */
const STATUS_MAP: Record<DocumentStatus, { label: string; className: string }> = {
  splitting: {
    label: '内容解析',
    className:
      'bg-cyan-100 text-cyan-800 border-cyan-300 dark:bg-cyan-950 dark:text-cyan-300 dark:border-cyan-800',
  },
  pending: {
    label: '等待中',
    className:
      'bg-default text-default-foreground border-border',
  },
  parsing: {
    label: '内容解析',
    className:
      'bg-cyan-100 text-cyan-800 border-cyan-300 dark:bg-cyan-950 dark:text-cyan-300 dark:border-cyan-800',
  },
  terminology: {
    label: '术语提取',
    className:
      'bg-orange-100 text-orange-800 border-orange-300 dark:bg-orange-950 dark:text-orange-300 dark:border-orange-800',
  },
  analyzing: {
    label: '多模态分析',
    className:
      'bg-purple-100 text-purple-800 border-purple-300 dark:bg-purple-950 dark:text-purple-300 dark:border-purple-800',
  },
  chunking: {
    label: '文档分块',
    className:
      'bg-indigo-100 text-indigo-800 border-indigo-300 dark:bg-indigo-950 dark:text-indigo-300 dark:border-indigo-800',
  },
  embedding: {
    label: '向量嵌入',
    className:
      'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800',
  },
  complete: {
    label: '已完成',
    className:
      'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-800',
  },
  failed: {
    label: '失败',
    className:
      'bg-danger-soft text-danger border-danger/30',
  },
}

function StatusLabelComponent({ status }: { status: DocumentStatus }) {
  const m = STATUS_MAP[status] || { label: status, className: 'bg-default text-default-foreground border-border' }
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${m.className}`}
    >
      {m.label}
    </span>
  )
}

export const StatusLabel = memo(StatusLabelComponent)
