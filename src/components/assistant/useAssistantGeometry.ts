import { useEffect, useState } from 'react'

const key = 'platform-assistant-geometry-v1'
const defaults = { offset: { x: 0, y: 0 }, size: { width: 430, height: 648 }, remember: true, degrade: true }
function restore() {
  try {
    const saved = JSON.parse(localStorage.getItem(key) || 'null')
    if (!saved || typeof saved.remember !== 'boolean') return defaults
    const valid = [saved.offset?.x, saved.offset?.y, saved.size?.width, saved.size?.height].every(Number.isFinite)
    return { ...defaults, remember: saved.remember, degrade: saved.degrade !== false,
      ...(valid && saved.remember ? { offset: { x: Math.min(0, Math.max(60 - window.innerWidth, saved.offset.x)), y: Math.min(0, Math.max(60 - window.innerHeight, saved.offset.y)) },
        size: { width: Math.max(320, Math.min(saved.size.width, window.innerWidth - 24)), height: Math.max(320, Math.min(saved.size.height, window.innerHeight - 104)) } } : {}) }
  } catch { return defaults }
}
export default function useAssistantGeometry() {
  const [geometry, setGeometry] = useState(restore)
  useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify(geometry.remember ? geometry : { ...geometry, offset: defaults.offset, size: defaults.size })) } catch { /* Storage may be unavailable. */ }
  }, [geometry])
  useEffect(() => {
    const clamp = () => setGeometry(value => ({ ...value,
      offset: { x: Math.min(0, Math.max(60 - window.innerWidth, value.offset.x)), y: Math.min(0, Math.max(60 - window.innerHeight, value.offset.y)) },
      size: { width: Math.max(280, Math.min(value.size.width, window.innerWidth - 24)), height: Math.max(280, Math.min(value.size.height, window.innerHeight - 104)) } }))
    window.addEventListener('resize', clamp)
    return () => window.removeEventListener('resize', clamp)
  }, [])
  return { geometry, setGeometry, reset: () => setGeometry(value => ({ ...value, offset: defaults.offset, size: defaults.size })) }
}
