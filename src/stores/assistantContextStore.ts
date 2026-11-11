import { useEffect } from 'react'
import { create } from 'zustand'

export type AssistantModule = 'overview' | 'skills' | 'developer' | 'knowledge' | 'assets' | 'workflow' | 'mcp'
export interface AssistantPageContext { module: AssistantModule; object_type?: 'skill' | 'knowledge_base' | 'asset'; object_id?: number }
export const useAssistantContextStore = create<{ object?: AssistantPageContext; setObject: (object?: AssistantPageContext) => void }>(set => ({
  setObject: object => set({ object }),
}))
export function useAssistantPageObject(module: AssistantModule, objectType: AssistantPageContext['object_type'], id?: string | number) {
  useEffect(() => {
    const objectId = Number(id)
    useAssistantContextStore.getState().setObject(Number.isInteger(objectId) && objectId > 0 ? { module, object_type: objectType, object_id: objectId } : undefined)
    return () => useAssistantContextStore.getState().setObject(undefined)
  }, [module, objectType, id])
}
