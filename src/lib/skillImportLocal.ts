import type { ImportLimits, ImportUpload } from '@/api/skillImport'

export interface CachedSkill {
  id: string; rootPath: string; sourceName: string; sourceSize: number; fileCount: number
  files: ImportUpload[]; mode: 'file' | 'directory' | 'zip'; archiveRoot?: string
  name: string; classId: string; application: string
  status: 'READY' | 'SUCCEEDED' | 'FAILED'; errors: string[]
  skillId?: number; revision?: number
  receipt?: { importId: string; itemId: string }; uploaded: boolean; baseImportId?: string
  validated?: boolean
}

const basename = (path: string) => path.split('/').filter(Boolean).pop() || 'SKILL'
const parent = (path: string) => path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '.'
const within = (path: string, root: string) => root === '.' || path.startsWith(root + '/')
const stem = (value: string) => value.replace(/\.(zip|md)$/i, '')
// ZIP's fallback code page; Chinese archives are decoded as GB18030 when applicable.
const zipCodePage = 'ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ '

function crc32(bytes: Uint8Array) {
  let value = -1
  for (const byte of bytes) {
    value ^= byte
    for (let i = 0; i < 8; i++) value = (value >>> 1) ^ (value & 1 ? 0xedb88320 : 0)
  }
  return (value ^ -1) >>> 0
}

export function decodeZipName(raw: Uint8Array, flags: number, extra = new Uint8Array()): string {
  if (flags & 0x800) return new TextDecoder('utf-8').decode(raw)
  const data = new DataView(extra.buffer, extra.byteOffset, extra.byteLength)
  for (let offset = 0; offset + 4 <= extra.length;) {
    const kind = data.getUint16(offset, true), length = data.getUint16(offset + 2, true)
    if (offset + 4 + length > extra.length) break
    if (kind === 0x7075 && length >= 5 && extra[offset + 4] === 1 && data.getUint32(offset + 5, true) === crc32(raw)) {
      try { return new TextDecoder('utf-8', { fatal: true }).decode(extra.subarray(offset + 9, offset + 4 + length)) } catch { /* use original bytes */ }
    }
    offset += 4 + length
  }
  try { return new TextDecoder('utf-8', { fatal: true }).decode(raw) } catch { /* legacy archive */ }
  try {
    const chinese = new TextDecoder('gb18030', { fatal: true }).decode(raw)
    if (/[\u3400-\u9fff\u{20000}-\u{2fa1f}]/u.test(chinese)) return chinese
  } catch { /* fallback to ZIP's code page */ }
  return Array.from(raw, byte => byte < 128 ? String.fromCharCode(byte) : zipCodePage[byte - 128]).join('')
}

interface ZipEntry { path: string; size: number; compressed: number; offset: number; method: number; flags: number }
function zipDirectory(bytes: Uint8Array, maxFiles: number): ZipEntry[] {
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  let end = bytes.length - 22
  while (end >= Math.max(0, bytes.length - 65557) && data.getUint32(end, true) !== 0x06054b50) end--
  if (end < Math.max(0, bytes.length - 65557)) throw new Error('ZIP目录不可读取')
  const count = data.getUint16(end + 10, true)
  let offset = data.getUint32(end + 16, true)
  if (count > maxFiles * 2 || count === 65535 || offset === 0xffffffff) throw new Error('ZIP目录过大')
  const result: ZipEntry[] = []
  for (let i = 0; i < count; i++) {
    if (offset + 46 > bytes.length || data.getUint32(offset, true) !== 0x02014b50) throw new Error('ZIP目录不可读取')
    const length = data.getUint16(offset + 28, true), extraLength = data.getUint16(offset + 30, true), comment = data.getUint16(offset + 32, true)
    const flags = data.getUint16(offset + 8, true)
    if (offset + 46 + length + extraLength + comment > bytes.length) throw new Error('ZIP目录不完整')
    const path = decodeZipName(bytes.subarray(offset + 46, offset + 46 + length), flags, bytes.subarray(offset + 46 + length, offset + 46 + length + extraLength))
    if (!path.endsWith('/')) result.push({path, flags, method: data.getUint16(offset + 10, true), size: data.getUint32(offset + 24, true), compressed: data.getUint32(offset + 20, true), offset: data.getUint32(offset + 42, true)})
    offset += 46 + length + extraLength + comment
  }
  return result
}

async function nestedZip(bytes: Uint8Array, entry: ZipEntry, remaining: number): Promise<Uint8Array> {
  if (entry.flags & 1 || entry.size > remaining) throw new Error('ZIP无法在本地展开')
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), offset = entry.offset
  if (offset + 30 > bytes.length || data.getUint32(offset, true) !== 0x04034b50) throw new Error('ZIP目录不可读取')
  const start = offset + 30 + data.getUint16(offset + 26, true) + data.getUint16(offset + 28, true)
  if (start + entry.compressed > bytes.length) throw new Error('ZIP目录不完整')
  const compressed = bytes.slice(start, start + entry.compressed)
  if (entry.method === 0) { if (compressed.length > remaining) throw new Error('ZIP过大'); return compressed }
  if (entry.method !== 8) throw new Error('ZIP压缩格式无法在本地展开')
  const reader = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader()
  const chunks: Uint8Array[] = []
  let total = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      total += value.length
      if (total > remaining) throw new Error('ZIP过大')
      chunks.push(value)
    }
  } finally { await reader.cancel() }
  const output = new Uint8Array(total)
  let position = 0
  for (const chunk of chunks) { output.set(chunk, position); position += chunk.length }
  return output
}

async function catalogZip(bytes: Uint8Array, limits: ImportLimits, budget: { bytes: number; files: number }, prefix = ''): Promise<{path:string;size:number}[]> {
  const entries = zipDirectory(bytes, limits.max_files)
  budget.files += entries.length
  if (budget.files > limits.max_files) throw new Error('ZIP目录过大')
  const roots = entries.filter(entry => basename(entry.path).toLowerCase() === 'skill.md').map(entry => parent(entry.path))
  const result: {path:string;size:number}[] = []
  for (const entry of entries) {
    if (entry.path.toLowerCase().endsWith('.zip') && !roots.some(root => within(entry.path, root))) {
      try {
        const inner = await nestedZip(bytes, entry, limits.max_batch_bytes - budget.bytes)
        budget.bytes += inner.length
        result.push(...await catalogZip(inner, limits, budget, prefix + entry.path + '/'))
        continue
      } catch { /* Keep the opaque entry; only the backend decides whether it is valid. */ }
    }
    result.push({path:prefix + entry.path,size:entry.size})
  }
  return result
}

function groups(entries: {path:string;size:number}[]) {
  const roots = entries.filter(entry => basename(entry.path).toLowerCase() === 'skill.md').map(entry => parent(entry.path))
  const result = roots.map(root => ({root, entries:entries.filter(entry => within(entry.path, root))}))
  const unassigned = entries.filter(entry => !roots.some(root => within(entry.path, root)))
  const extras = new Map<string, typeof entries>()
  for (const entry of unassigned) {
    const root = roots.length ? parent(entry.path) : entry.path.includes('/') ? entry.path.split('/')[0] : entry.path
    extras.set(root, [...extras.get(root) ?? [], entry])
  }
  result.push(...Array.from(extras, ([root, values]) => ({root, entries:values})))
  return result
}

function cached(sourceName: string, rootPath: string, files: ImportUpload[], mode: CachedSkill['mode'], fileCount: number, archiveRoot?: string): CachedSkill {
  return {id:crypto.randomUUID().replaceAll('-', ''), rootPath, sourceName, sourceSize:files.reduce((sum,row) => sum + row.file.size,0), fileCount,
    files, mode, archiveRoot, name:stem(rootPath === '.' ? sourceName : basename(rootPath)),classId:'',application:'',status:'READY',errors:[],uploaded:false}
}

/** Read directory structure for the browser queue. Never uploads or validates YAML. */
export async function cacheSkillFiles(files: ImportUpload[], directory: boolean, limits: ImportLimits): Promise<CachedSkill[]> {
  if (!files.length) throw new Error('所选文件夹为空，请重新选择。')
  if (files.length > limits.max_files || files.reduce((sum,row) => sum + row.file.size,0) > limits.max_batch_bytes) throw new Error('所选文件超过浏览器暂存大小或数量限制，请减少文件后重试。')
  const rootFiles = files.filter(row => basename(row.path).toLowerCase() === 'skill.md').map(row => parent(row.path))
  const archives = files.filter(row => row.path.toLowerCase().endsWith('.zip') && !rootFiles.some(root => within(row.path,root)))
  const ordinary = files.filter(row => !archives.includes(row))
  const result: CachedSkill[] = []
  for (const archive of archives) {
    try {
      if (archive.file.size > limits.max_file_bytes) throw new Error('ZIP过大，不在浏览器展开')
      const entries = await catalogZip(new Uint8Array(await archive.file.arrayBuffer()), limits, {bytes:0,files:0})
      const discovered = groups(entries)
      if (!discovered.length) throw new Error('空ZIP')
      for (const group of discovered) result.push(cached(archive.path, group.root, [{file:archive.file,path:archive.file.name}], 'zip',group.entries.length,group.root))
    } catch { result.push(cached(archive.path, stem(archive.file.name), [{file:archive.file,path:archive.file.name}], 'zip',1)) }
  }
  for (const group of groups(ordinary.map(row => ({path:row.path,size:row.file.size})))) {
    const selected = ordinary.filter(row => group.entries.some(entry => entry.path === row.path))
    const single = !directory && selected.length === 1 && !selected[0].path.includes('/')
    result.push(cached(single ? selected[0].file.name : group.root, group.root, selected, single ? 'file' : 'directory', selected.length))
  }
  return result
}

/** Queue removal only releases browser references; imported backend drafts are untouched. */
export function removeCachedSkill(rows: CachedSkill[], id: string) { return rows.filter(row => row.id !== id) }

export function mergeCachedSkills(rows: CachedSkill[], incoming: CachedSkill[], previous: CachedSkill[] = rows) {
  const result = [...rows]
  for (const row of incoming) {
    let matches = previous.filter(old => old.rootPath === row.rootPath && old.sourceName === row.sourceName)
    if (!matches.length) matches = previous.filter(old => old.rootPath === row.rootPath)
    const old = matches.length === 1 ? matches[0] : previous.length === 1 && incoming.length === 1 && previous[0].skillId ? previous[0] : undefined
    const next = old ? {...row,id:old.id,name:old.name,classId:old.classId,application:old.application,skillId:old.skillId,revision:old.revision,
      baseImportId:old.baseImportId ?? old.receipt?.importId} : row
    const index = result.findIndex(item => item.id === next.id)
    if (index < 0) result.push(next); else result[index] = next
  }
  return result
}
