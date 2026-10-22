import { create } from 'zustand'
import type { Implementation } from '@/types/developer'
import { getDeveloperMetadata, listDeveloperSkills, type DeveloperCatalogOption } from '@/api/developerCenter'

interface DeveloperState {
  implementations: Implementation[]
  skillClasses: DeveloperCatalogOption[]
  applications: DeveloperCatalogOption[]
  loading: boolean
  load: () => Promise<void>
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
  load: async () => {
    set({ loading: true })
    try {
      const [implementations, metadata] = await Promise.all([listDeveloperSkills(), getDeveloperMetadata()])
      set({ implementations, skillClasses: metadata.skill_classes, applications: metadata.applications })
    }
    finally { set({ loading: false }) }
  },
  replace: item => set(state => ({ implementations: state.implementations.some(row => row.id === item.id) ? state.implementations.map(row => row.id === item.id ? item : row) : [item, ...state.implementations] })),
  patch: (id, changes) => set(state => ({ implementations: state.implementations.map(row => row.id === id ? { ...row, ...changes } : row) })),
  remove: id => set(state => ({ implementations: state.implementations.filter(row => row.id !== id) })),
}))
