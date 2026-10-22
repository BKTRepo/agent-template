export interface ZipEntry { path: string; data: Uint8Array }
const encoder = new TextEncoder()
const crcTable = Array.from({ length: 256 }, (_, index) => {
  let value = index
  for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
  return value >>> 0
})
function crc32(bytes: Uint8Array) {
  let value = 0xffffffff
  for (const byte of bytes) value = crcTable[(value ^ byte) & 255] ^ (value >>> 8)
  return (value ^ 0xffffffff) >>> 0
}
// 标准 ZIP STORE 格式，UTF-8 路径与 CRC32；无需联网或额外压缩服务。
export function createZip(entries: ZipEntry[]): Blob {
  if (entries.length > 65535) throw new Error('ZIP 文件数量超出限制')
  const local: Uint8Array<ArrayBuffer>[] = [], central: Uint8Array<ArrayBuffer>[] = []
  const paths = new Set<string>()
  let offset = 0, centralSize = 0
  for (const entry of entries) {
    if (!entry.path || /(^\/|\\|(^|\/)\.\.(\/|$)|\x00)/.test(entry.path) || paths.has(entry.path)) throw new Error('ZIP 路径无效或重复')
    paths.add(entry.path)
    const name = encoder.encode(entry.path), data = Uint8Array.from(entry.data)
    if (name.length > 65535 || data.length > 0xffffffff || offset + data.length > 0xffffffff) throw new Error('ZIP 文件大小超出限制')
    const crc = crc32(data)
    const header = new Uint8Array(30 + name.length), view = new DataView(header.buffer)
    view.setUint32(0, 0x04034b50, true); view.setUint16(4, 20, true); view.setUint16(6, 0x800, true)
    view.setUint16(12, 33, true); view.setUint32(14, crc, true); view.setUint32(18, data.length, true); view.setUint32(22, data.length, true); view.setUint16(26, name.length, true)
    header.set(name, 30); local.push(header, data)
    const directory = new Uint8Array(46 + name.length), centralView = new DataView(directory.buffer)
    centralView.setUint32(0, 0x02014b50, true); centralView.setUint16(4, 20, true); centralView.setUint16(6, 20, true); centralView.setUint16(8, 0x800, true)
    centralView.setUint16(14, 33, true); centralView.setUint32(16, crc, true); centralView.setUint32(20, data.length, true); centralView.setUint32(24, data.length, true); centralView.setUint16(28, name.length, true); centralView.setUint32(42, offset, true)
    directory.set(name, 46); central.push(directory); centralSize += directory.length; offset += header.length + data.length
  }
  const end = new Uint8Array(22), endView = new DataView(end.buffer)
  endView.setUint32(0, 0x06054b50, true); endView.setUint16(8, entries.length, true); endView.setUint16(10, entries.length, true); endView.setUint32(12, centralSize, true); endView.setUint32(16, offset, true)
  return new Blob([...local, ...central, end], { type: 'application/zip' })
}
