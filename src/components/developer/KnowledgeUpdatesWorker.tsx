import { useEffect } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { useKnowledgeUpdatesStore } from '@/stores/knowledgeUpdatesStore'

export default function KnowledgeUpdatesWorker() {
  const token = useAuthStore(state => state.session?.token)
  useEffect(() => {
    const store = useKnowledgeUpdatesStore.getState()
    store.reset()
    let disposed = false, running = false
    const refresh = async () => {
      if (disposed || running || document.visibilityState === 'hidden') return
      running = true
      try { await store.refresh() } catch { /* Keep the last confirmed count until the next refresh. */ }
      finally { running = false }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 15000)
    const onFocus = () => void refresh()
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      disposed = true; window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
      store.reset()
    }
  }, [token])
  return null
}
