import { create } from 'zustand'
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
  replace: (item: Implementation) => void
  patch: (id: string, changes: Partial<Implementation>) => void
  remove: (id: string) => void
}

// 业务记录只来自后端。页面刷新后重新查询数据库，不使用浏览器持久化记录。
export const useDeveloperStore = create<DeveloperState>((set) => ({
  implementations: [],
  skillClasses: [],
  applications: [],
  loading: false,
  page: 1,
  pageSize: 10,
  total: 0,
  pages: 1,
  load: async (requestedPage = 1) => {
    set({ loading: true })
    try {
      const state = useDeveloperStore.getState()
      const page = Math.max(1, Math.min(requestedPage, Math.max(1, state.pages)))
      const [result, metadata] = await Promise.all([listDeveloperSkillsPage(page, state.pageSize), getDeveloperMetadata()])
      setApplicationCatalog(metadata.applications)
      set({ implementations: result.items, skillClasses: metadata.skill_classes, applications: metadata.applications,
        page: result.page, pageSize: result.pageSize, total: result.total, pages: Math.max(1, result.pages) })
    }
    finally { set({ loading: false }) }
  },
  replace: item => set(state => ({ implementations: state.implementations.some(row => row.id === item.id) ? state.implementations.map(row => row.id === item.id ? item : row) : [item, ...state.implementations] })),
  patch: (id, changes) => set(state => ({ implementations: state.implementations.map(row => row.id === id ? { ...row, ...changes } : row) })),
  remove: id => set(state => ({ implementations: state.implementations.filter(row => row.id !== id) })),
}))
