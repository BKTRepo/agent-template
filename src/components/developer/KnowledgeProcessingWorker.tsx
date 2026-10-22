import { useEffect } from 'react'
import { useKnowledgeStore } from '@/stores/knowledgeStore'

export default function KnowledgeProcessingWorker() {
  const items = useKnowledgeStore(state => state.knowledgeBases)
  useEffect(() => {
    const timers = items.filter(item => item.processingStatus === '知识处理中' && item.processingJobId).map(item => window.setTimeout(() => useKnowledgeStore.getState().finishProcessing(item.id, item.processingJobId!), 1800))
    return () => timers.forEach(window.clearTimeout)
  }, [items])
  return null
}
