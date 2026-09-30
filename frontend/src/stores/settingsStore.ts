import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { createSelectors } from '@/lib/createSelectors'
import { DEFAULT_THEME_COLOR, type ThemeMode } from '@/lib/theme'
import { DEFAULT_LLM_MODEL } from '@/lib/constants'

export type TabId = 'knowledge' | 'chat' | 'api'

interface SettingsState {
  /** 主题模式: 亮色 / 暗色 / 跟随系统 */
  themeMode: ThemeMode
  /** 主题色（THEME_COLORS 的 key），用于覆盖 --accent */
  accentColor: string
  activeTab: TabId
  chatMode: 'naive' | 'hybrid' | 'bypass'
  /** 对话使用的 LLM 模型 */
  llmModel: string
  /** 向量检索(naive 模式)稠密检索条数 */
  naiveTopK: number
  /** 混合检索(hybrid 模式) RRF 融合保留条数（重排候选池） */
  rrfTopK: number
  denseTopK: number
  bm25TopK: number
  responseType: string
  enableRerank: boolean
  includeRefs: boolean
  streamEnabled: boolean
  temperature: number
  setThemeMode: (mode: ThemeMode) => void
  setAccentColor: (key: string) => void
  setActiveTab: (tab: TabId) => void
  setChatMode: (mode: 'naive' | 'hybrid' | 'bypass') => void
  setLlmModel: (model: string) => void
  setNaiveTopK: (k: number) => void
  setRrfTopK: (k: number) => void
  setDenseTopK: (k: number) => void
  setBm25TopK: (k: number) => void
  setResponseType: (t: string) => void
  setEnableRerank: (v: boolean) => void
  setIncludeRefs: (v: boolean) => void
  setStreamEnabled: (v: boolean) => void
  setTemperature: (t: number) => void
  resetAllSettings: () => void
}

const defaults = {
  chatMode: 'hybrid' as const,
  llmModel: DEFAULT_LLM_MODEL,
  // 向量检索(naive): 稠密检索返回条数
  naiveTopK: 100,
  // 混合检索(hybrid): 向量/BM25 召回各取 Top 100, RRF 融合后保留 Top 100 作为重排候选池
  // （重排精选 50 条为最终窗口, 由后端 RERANK_TOP_K 控制）
  rrfTopK: 100,
  denseTopK: 100,
  bm25TopK: 100,
  responseType: '多段落',
  enableRerank: true,
  includeRefs: false,
  streamEnabled: true,
  temperature: 0.7,
}

const useSettingsStoreBase = create<SettingsState>()(
  persist(
    (set) => ({
      // 首次进入（无持久化记录）默认跟随系统; 用户手动切换后由 persist 记住其选择
      themeMode: 'system' as ThemeMode,
      accentColor: DEFAULT_THEME_COLOR,
      activeTab: 'knowledge' as TabId,
      ...defaults,
      setThemeMode: (themeMode) => set({ themeMode }),
      setAccentColor: (accentColor) => set({ accentColor }),
      setActiveTab: (activeTab) => set({ activeTab }),
      setChatMode: (chatMode) => set({ chatMode }),
      setLlmModel: (llmModel) => set({ llmModel }),
      setNaiveTopK: (naiveTopK) => set({ naiveTopK }),
      setRrfTopK: (rrfTopK) => set({ rrfTopK }),
      setDenseTopK: (denseTopK) => set({ denseTopK }),
      setBm25TopK: (bm25TopK) => set({ bm25TopK }),
      setResponseType: (responseType) => set({ responseType }),
      setEnableRerank: (enableRerank) => set({ enableRerank }),
      setIncludeRefs: (includeRefs) => set({ includeRefs }),
      setStreamEnabled: (streamEnabled) => set({ streamEnabled }),
      setTemperature: (temperature) => set({ temperature }),
      resetAllSettings: () => set({ ...defaults }),
    }),
    {
      name: 'rag-test-jyy-settings',
      // v6: 两模式共用的 topK 拆分为 naiveTopK（向量检索）与 rrfTopK（RRF 融合）
      // v5: RRF 合并 Top-K（重排候选池）50→100; 最终窗口改由后端 RERANK_TOP_K 控制
      // v4: 混合检索默认值 向量/BM25 Top-K 60→100、RRF 合并 Top-K 60→50
      // v3: theme -> themeMode + accentColor; v2: 三个 Top-K 提到 60、重排默认开启
      version: 6,
      migrate: (persistedState, version) => {
        const state = persistedState as Partial<SettingsState> & { theme?: 'light' | 'dark'; topK?: number }
        if (version < 2) {
          // v0/v1 → v2: 三个 Top-K 默认统一提到 60、重排默认开启
          if (state.topK === 20) state.topK = 60
          if (state.denseTopK === 40) state.denseTopK = 60
          if (state.bm25TopK === 40) state.bm25TopK = 60
          state.enableRerank = true
        }
        if (version < 3) {
          // 旧版 theme(light/dark) 迁移为 themeMode；新增主题色默认蓝色
          state.themeMode = state.theme ?? 'light'
          state.accentColor = state.accentColor ?? DEFAULT_THEME_COLOR
          delete state.theme
        }
        if (version < 4) {
          // v3 → v4: 混合检索默认值调整（仅迁移仍为旧默认 60 的项, 用户自定义值保留）
          if (state.topK === 60) state.topK = 50
          if (state.denseTopK === 60) state.denseTopK = 100
          if (state.bm25TopK === 60) state.bm25TopK = 100
        }
        if (version < 5) {
          // v4 → v5: 候选池扩容 50→100（仅迁移仍为旧默认 50 的项, 用户自定义值保留）
          if (state.topK === 50) state.topK = 100
        }
        if (version < 6) {
          // v5 → v6: 两模式共用的 topK 拆分为 naiveTopK 与 rrfTopK,
          // 旧值原样带入两侧, 拆分前后两模式行为不变
          state.naiveTopK = state.topK ?? 100
          state.rrfTopK = state.topK ?? 100
          delete state.topK
        }
        return state as SettingsState
      },
    },
  ),
)

export const useSettingsStore = createSelectors(useSettingsStoreBase)
