import { create } from 'zustand'
import { useAuthStore } from './authStore'
import { setApplicationCatalog } from '@/lib/access'
import type { Implementation } from '@/types/developer'
import { getDeveloperMetadata, listDeveloperSkillsPage, type DeveloperCatalogOption } from '@/api/developerCenter'

interface DeveloperState {
  implementations: Implementation[]
  skillClasses: DeveloperCatalogOption[]
  applications: DeveloperCatalogOption[]
  loading: boolean
  page: number
  pageSize: number
  total: number
  pages: number
  load: (page?: number) => Promise<void>
  refresh: (page?: number) => Promise<void>
  replace: (item: Implementation) => void
  patch: (id: string, changes: Partial<Implementation>) => void
  remove: (id: string) => void
}

let requestSequence = 0
async function readPage(requestedPage: number, silent: boolean): Promise<void> {
  const state = useDeveloperStore.getState()
  if (silent && state.loading) return
  const token = useAuthStore.getState().session?.token, sequence = ++requestSequence
  const current = () => sequence === requestSequence && useAuthStore.getState().session?.token === token
  if (!silent) useDeveloperStore.setState({ loading: true })
  try {
    const [result, metadata] = await Promise.all([
      listDeveloperSkillsPage(Math.max(1, requestedPage), state.pageSize),
      silent ? Promise.resolve(undefined) : getDeveloperMetadata(),
    ])
    if (!current()) return
    if (metadata) setApplicationCatalog(metadata.applications)
    useDeveloperStore.setState({ implementations: result.items, page: result.page, pageSize: result.pageSize,
      total: result.total, pages: Math.max(1, result.pages),
      ...(metadata ? { skillClasses: metadata.skill_classes, applications: metadata.applications } : {}) })
  } finally { if (!silent && current()) useDeveloperStore.setState({ loading: false }) }
}
// 列表和总数始终来自后端；静默刷新保留当前内容和页码。
export const useDeveloperStore = create<DeveloperState>((set) => ({
  implementations: [],
  skillClasses: [],
  applications: [],
  loading: false,
  page: 1,
  pageSize: 10,
  total: 0,
  pages: 1,
  load: (requestedPage = 1) => readPage(requestedPage, false),
  refresh: (requestedPage?: number): Promise<void> => readPage(requestedPage ?? useDeveloperStore.getState().page, true),
  replace: item => set(state => ({ implementations: state.implementations.some(row => row.id === item.id) ? state.implementations.map(row => row.id === item.id ? item : row) : [item, ...state.implementations].slice(0, state.pageSize) })),
  patch: (id, changes) => set(state => ({ implementations: state.implementations.map(row => row.id === id ? { ...row, ...changes } : row) })),
  remove: id => set(state => ({ implementations: state.implementations.filter(row => row.id !== id) })),
}))
