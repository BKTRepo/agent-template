export function descriptionLines(description: string | undefined | null): string[] {
  const characters = Array.from((description || '').replace(/\s+/gu, ' ').trim())
  if (!characters.length) return []
  const visible = characters.length > 44 ? [...characters.slice(0, 41), '.', '.', '.'] : characters
  return [visible.slice(0, 22).join(''), visible.slice(22).join('')].filter(Boolean)
}
