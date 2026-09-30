/**
 * 将大体积 markdown 切分为若干有上限的块, 供渐进式渲染（见 ProgressiveMarkdown）。
 *
 * 切分只发生在**安全的块边界**——标题行或空行处, 且绝不切断代码栅栏
 * （``` / ~~~ 围栏内部不切）。GFM 表格的行之间没有空行, 因此整张表会完整
 * 落在同一块内, 不会被拦腰截断。这样每一块都是自洽的块序列, 可独立交给
 * ReactMarkdown 渲染而不破坏结构。
 *
 * 兜底: 若某个块（如一张超大表格）迟迟遇不到空行/标题, 达到硬上限时也强制
 * 切出（仅在栅栏外）, 避免单块无限膨胀导致单次渲染仍然卡顿。
 */

/** 单块目标上限（字符）。达到后在下一个安全边界切块。 */
export const MARKDOWN_CHUNK_TARGET = 50_000

/** 硬上限（目标上限的倍数）。超过即在任意行强制切块（栅栏外）。 */
const HARD_LIMIT_FACTOR = 6

const FENCE_RE = /^(```|~~~)/
const HEADING_RE = /^#{1,6}\s/

export function splitMarkdownIntoChunks(
  markdown: string,
  maxChunkChars: number = MARKDOWN_CHUNK_TARGET,
): string[] {
  if (!markdown) return []

  const hardLimit = maxChunkChars * HARD_LIMIT_FACTOR
  const lines = markdown.split('\n')
  const chunks: string[] = []

  let current: string[] = []
  let currentLen = 0
  let inFence = false
  let fenceChar = ''

  const flush = () => {
    if (current.length > 0) {
      chunks.push(current.join('\n'))
      current = []
      currentLen = 0
    }
  }

  for (const line of lines) {
    const trimmed = line.trimStart()
    const isBlank = trimmed === ''
    const isHeading = !inFence && HEADING_RE.test(trimmed)
    const isTableRow = !inFence && trimmed.startsWith('|')
    const fenceMatch = trimmed.match(FENCE_RE)

    // 到达目标上限后遇到标题: 标题作为新块的起点（段落/章节自然分界）
    if (isHeading && currentLen >= maxChunkChars) {
      flush()
    }

    current.push(line)
    currentLen += line.length + 1

    // 维护栅栏状态（围栏标记行本身属于代码块, 先计入再切换状态）
    if (fenceMatch) {
      const markerChar = fenceMatch[1][0]
      if (!inFence) {
        inFence = true
        fenceChar = markerChar
      } else if (markerChar === fenceChar) {
        inFence = false
        fenceChar = ''
      }
    }

    // 栅栏外的空行是块分隔符: 达到目标上限即在此切块
    if (!inFence && isBlank && currentLen >= maxChunkChars) {
      flush()
      continue
    }

    // 兜底: 超长无空行区域强制切出, 防止单块无限膨胀。
    // 跳过表格行（GFM 表格行间无空行, 强行切会破坏表格）——超大表格宁可整块
    // 保留也不拦腰截断, 其前后仍有空行边界保证其余内容正常分块。
    if (!inFence && !isTableRow && currentLen >= hardLimit) {
      flush()
    }
  }

  flush()
  return chunks
}
