import { ToastProvider } from '@heroui/react'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import SiteHeader from '@/components/layout/SiteHeader'
import KnowledgePage from '@/pages/KnowledgePage'
import ChatPage from '@/pages/ChatPage'
import { ApiPage } from '@/pages/ApiPage'
import { useSettingsStore } from '@/stores/settingsStore'
import { useTheme } from '@/hooks/useTheme'

/**
 * 页面外壳。页签切换直接依据 settingsStore.activeTab 条件渲染对应页面
 * （与原 Radix Tabs 的"切换即卸载/挂载"行为一致）；导航栏滑块在 SiteHeader
 * 内以自定义方式实现，不依赖 react-aria 的 SelectionIndicator，稳定且离线可用。
 */
export default function App() {
  useTheme()
  const activeTab = useSettingsStore.use.activeTab()

  return (
    <ErrorBoundary>
      <div className="flex h-screen w-screen flex-col gap-0 overflow-hidden bg-background">
        {/* 顶部导航（品牌 + 滑块页签 + 明暗/主题色 + 用户） */}
        <SiteHeader />

        {/* 页面内容区：按当前页签条件渲染，绝对定位铺满 */}
        <div className="relative min-h-0 flex-1">
          {activeTab === 'knowledge' && (
            <div className="absolute inset-0 overflow-auto">
              <KnowledgePage />
            </div>
          )}
          {activeTab === 'chat' && (
            <div className="absolute inset-0 overflow-hidden">
              <ChatPage />
            </div>
          )}
          {activeTab === 'api' && (
            <div className="absolute inset-0 overflow-hidden">
              <ApiPage />
            </div>
          )}
        </div>
      </div>

      {/* HeroUI Toast 通知区域（全局, 替代 sonner） */}
      <ToastProvider placement="bottom" />
    </ErrorBoundary>
  )
}
