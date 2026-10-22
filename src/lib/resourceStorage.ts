// 二进制文件存入 IndexedDB；列表/草稿仅保存元信息，避免 localStorage 丢失文件内容。
function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('znfwdd-resource-files', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('files')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(new Error('文件存储不可用，请检查浏览器存储设置'))
  })
}
export async function saveBlobs(items: { key: string; blob: Blob }[]) {
  if (!items.length) return
  const database = await openDatabase()
  try { await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction('files', 'readwrite')
    items.forEach(item => transaction.objectStore('files').put(item.blob, item.key))
    transaction.oncomplete = () => resolve()
    transaction.onabort = transaction.onerror = () => reject(new Error('文件保存失败，可能超出浏览器存储容量'))
  }) } finally { database.close() }
}
export async function readBlob(key: string): Promise<Blob | undefined> {
  const database = await openDatabase()
  try { return await new Promise((resolve, reject) => {
    const request = database.transaction('files', 'readonly').objectStore('files').get(key)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(new Error('文件读取失败'))
  }) } finally { database.close() }
}
export function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a'); link.href = url; link.download = name; link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
