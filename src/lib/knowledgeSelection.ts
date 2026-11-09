/** Compare persisted knowledge IDs consistently across JSON numbers and strings. */
export const knowledgeIdentity = (id: string | number): string => String(id).trim().replace(/^0+(?=\d+$)/, '')

export function uniqueKnowledgeSelections<T extends { id: string | number }>(items: T[]): (T & { id: string })[] {
  const seen = new Set<string>()
  return items.flatMap(item => {
    const id = knowledgeIdentity(item.id)
    if (seen.has(id)) return []
    seen.add(id)
    return [{ ...item, id }]
  })
}

export function hasDuplicateKnowledge(ids: (string | number)[]): boolean {
  return new Set(ids.map(knowledgeIdentity)).size !== ids.length
}
