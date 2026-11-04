import { useEffect } from 'react'
import { useKnowledgeStore } from '@/stores/knowledgeStore'
import { useAccessStore } from '@/stores/accessStore'

export default function KnowledgeProcessingWorker() {
  const actor = useAccessStore(state => state.actor.id)
  useEffect(() => {
    useKnowledgeStore.getState().reset()
    if (!actor) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    async function poll() {
      await useKnowledgeStore.getState().refreshProcessing(controller.signal)
      if (!controller.signal.aborted) timer = setTimeout(poll, 3000)
    }
    void useKnowledgeStore.getState().load().then(() => { if (!controller.signal.aborted) void poll() })
    return () => { controller.abort(); if (timer) clearTimeout(timer) }
  }, [actor])
  return null
}
