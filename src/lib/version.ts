export function nextVersion(value: string, prefix = '') {
  const match = /^[vV]?(\d+)\.(\d+)(?:\.(\d+))?$/.exec(value.trim())
  if (!match) throw new Error('历史版本格式无法自动递增，请联系数据维护人员修正。')
  const parts = [Number(match[1]), Number(match[2]), Number(match[3] ?? 0) + 1]
  if (parts.some(part => !Number.isSafeInteger(part))) throw new Error('版本号超出系统范围。')
  return `${prefix}${parts.join('.')}`
}
