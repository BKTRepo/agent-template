export function formatSkillClassDescription(description: string | undefined | null): string {
  return (description ?? '').replace(/\\r\\n|\\n|\r\n?/g, '\n')
}

export function descriptionLines(description: string | undefined | null): string[] {
  const value = (description ?? '').replace(/\r\n?/g, '\n').trim()
  if (!value) return []
  const lines = value.split('\n').flatMap(line => line.replace(/\s+/gu, ' ').trim().match(/.{1,22}/gu) ?? [''])
  if (lines.length <= 2) return lines
  return [lines[0], Array.from(lines[1]).slice(0, 19).join('') + '...']
}
