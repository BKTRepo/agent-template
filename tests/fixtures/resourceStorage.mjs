const blobs = new Map()
export let downloaded
export async function saveBlobs(items) { items.forEach(item => blobs.set(item.key, item.blob)) }
export async function readBlob(key) { return blobs.get(key) }
export function downloadBlob(blob, name) { downloaded = { blob, name } }
