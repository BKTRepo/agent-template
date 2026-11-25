import { useEffect } from 'react'
import { create } from 'zustand'
import { getSkillClassMetadata } from '@/api/skillClasses'
import { useAuthStore } from './authStore'
import type { SkillClassOption, TestStage } from '@/types/skillClass'

interface ClassCatalogState {
  classes: SkillClassOption[]; stages: TestStage[]; version: number; error: string
  refresh: () => Promise<void>; invalidate: () => void
}
let sequence = 0
let pending: Promise<void> | undefined
const identity = () => { const session = useAuthStore.getState().session; return `${session?.username}:${session?.token}` }
export const useSkillClassStore = create<ClassCatalogState>((set) => ({
  classes: [], stages: [], version: 0, error: '',
  refresh: () => {
    if (pending) return pending
    const account = identity(), current = ++sequence
    const work = getSkillClassMetadata().then(data => {
      if (current === sequence && account === identity()) set({ classes: data.skill_classes, stages: data.test_stages, error: '' })
    }).catch(error => {
      if (current === sequence && account === identity()) set({ error: (error as Error).message })
      throw error
    }).finally(() => { if (pending === work) pending = undefined })
    pending = work
    return work
  },
  invalidate: () => { sequence++; pending = undefined; set(state => ({ version: state.version + 1 })) },
}))
useAuthStore.subscribe((next, previous) => {
  if (next.session?.token !== previous.session?.token || next.session?.username !== previous.session?.username) {
    sequence++; pending = undefined
    useSkillClassStore.setState(state => ({ classes: [], stages: [], error: '', version: state.version + 1 }))
  }
})

export function useSkillClassCatalog() {
  const state = useSkillClassStore()
  useEffect(() => {
    const refresh = () => { void state.refresh().catch(() => {}) }
    refresh()
    window.addEventListener('focus', refresh)
    return () => window.removeEventListener('focus', refresh)
  }, [state.version, state.refresh])
  return state
}
