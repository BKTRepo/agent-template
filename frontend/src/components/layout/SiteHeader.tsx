import { useEffect, useLayoutEffect, useRef, useCallback, useState } from 'react'
import {
  Sun, Moon, Monitor, BookOpen, MessageCircle, Code, Palette, Check,
} from 'lucide-react'
import {
  Button,
  Popover, PopoverTrigger, PopoverContent, PopoverDialog,
} from '@heroui/react'
import { useSettingsStore, type TabId } from '@/stores/settingsStore'
import { THEME_COLORS, type ThemeMode } from '@/lib/theme'
import { cn } from '@/lib/utils'

const TABS: { id: TabId; label: string; Icon: typeof BookOpen }[] = [
  { id: 'knowledge', label: '知识库', Icon: BookOpen },
  { id: 'chat', label: '对话问答', Icon: MessageCircle },
  { id: 'api', label: 'API', Icon: Code },
]

const MODES: { key: ThemeMode; label: string; Icon: typeof Sun }[] = [
  { key: 'light', label: '浅色', Icon: Sun },
  { key: 'dark', label: '深色', Icon: Moon },
  { key: 'system', label: '跟随系统', Icon: Monitor },
]

/**
 * 导航页签（自定义滑块）。
 * 通过测量选中页签的位置/宽度，渲染一个绝对定位的"胶囊滑块"，切换时以 CSS
 * transition 平滑滑动。相比 react-aria SelectionIndicator，此实现不依赖
 * SharedElementTransition，稳定且完全离线。
 */
function NavTabs() {
  const activeTab = useSettingsStore.use.activeTab()
  const setActiveTab = useSettingsStore.use.setActiveTab()
  const listRef = useRef<HTMLDivElement>(null)
  const [pill, setPill] = useState({ left: 0, width: 0, ready: false })

  const updatePill = useCallback(() => {
    const list = listRef.current
    if (!list) return
    const active = list.querySelector<HTMLElement>(`[data-tab-id="${activeTab}"]`)
    if (!active) return
    const listRect = list.getBoundingClientRect()
    const activeRect = active.getBoundingClientRect()
    setPill({ left: activeRect.left - listRect.left, width: activeRect.width, ready: true })
  }, [activeTab])

  // 首次布局后与页签变化时更新滑块位置
  useLayoutEffect(() => {
    updatePill()
  }, [updatePill])

  // 窗口尺寸变化时重新测量
  useEffect(() => {
    window.addEventListener('resize', updatePill)
    return () => window.removeEventListener('resize', updatePill)
  }, [updatePill])

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label="主导航"
      className="relative inline-flex items-center rounded-full bg-default p-1"
    >
      {/* 滑块（选中页签背后的胶囊） */}
      <span
        aria-hidden
        className={cn(
          'absolute rounded-full bg-segment shadow-surface transition-[left,width] duration-300 ease-out',
          !pill.ready && 'opacity-0',
        )}
        style={{ left: pill.left, width: pill.width, top: '4px', bottom: '4px' }}
      />
      {TABS.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          role="tab"
          data-tab-id={id}
          aria-selected={activeTab === id}
          onClick={() => setActiveTab(id)}
          className={cn(
            'relative z-10 flex h-8 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-5 text-sm font-medium outline-none transition-colors',
            'focus-visible:ring-2 focus-visible:ring-focus',
            activeTab === id ? 'text-segment-foreground' : 'text-muted hover:text-foreground',
          )}
        >
          <Icon className="size-4" />
          {label}
        </button>
      ))}
    </div>
  )
}

/** 明暗模式切换：浅色 / 深色 / 跟随系统（分段胶囊按钮组） */
function ThemeModeToggle() {
  const themeMode = useSettingsStore.use.themeMode()
  const setThemeMode = useSettingsStore.use.setThemeMode()
  return (
    <div className="inline-flex items-center gap-0.5 overflow-hidden rounded-full border border-border bg-default p-0.5">
      {MODES.map(({ key, label, Icon }) => (
        <button
          key={key}
          type="button"
          aria-label={label}
          title={label}
          onClick={() => setThemeMode(key)}
          className={cn(
            'flex size-7 items-center justify-center rounded-full outline-none transition-colors',
            'focus-visible:ring-2 focus-visible:ring-focus',
            themeMode === key
              ? 'bg-accent text-accent-foreground shadow-sm'
              : 'text-muted hover:text-foreground',
          )}
        >
          <Icon className="size-4" />
        </button>
      ))}
    </div>
  )
}

/** 主题色选择：弹出面板内置本地色板（oklch 颜色, 无外链资源） */
function ThemeColorPicker() {
  const accentColor = useSettingsStore.use.accentColor()
  const setAccentColor = useSettingsStore.use.setAccentColor()
  return (
    <Popover>
      <PopoverTrigger>
        <Button variant="ghost" size="sm" isIconOnly aria-label="主题色" className="text-muted">
          <Palette className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent>
        <PopoverDialog>
          <div className="p-3">
            <p className="mb-2 text-xs font-medium text-foreground">主题色</p>
            <div className="grid grid-cols-4 gap-2">
              {THEME_COLORS.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  title={c.label}
                  aria-label={c.label}
                  onClick={() => setAccentColor(c.key)}
                  className={cn(
                    'flex size-8 items-center justify-center rounded-full outline-none transition-transform hover:scale-110',
                    'focus-visible:ring-2 focus-visible:ring-focus',
                    accentColor === c.key && 'ring-2 ring-foreground ring-offset-2 ring-offset-overlay',
                  )}
                  style={{ backgroundColor: c.accent }}
                >
                  {accentColor === c.key && <Check className="size-4 text-white" />}
                </button>
              ))}
            </div>
          </div>
        </PopoverDialog>
      </PopoverContent>
    </Popover>
  )
}

export default function SiteHeader() {
  return (
    <header className="sticky top-0 z-50 flex h-14 w-full shrink-0 items-center border-b border-border bg-surface px-4 shadow-surface">
      {/* 左侧品牌：RAG 字标（Space Grotesk 粗体 + 主题色渐变, 本地字体） */}
      <div className="flex min-w-[170px] items-center">
        <span className="rag-logo" aria-label="RAG">
          RAG
        </span>
      </div>

      {/* 中部导航：自定义滑块页签 */}
      <div className="flex flex-1 items-center justify-center">
        <NavTabs />
      </div>

      {/* 右侧：明暗模式 + 主题色 */}
      <div className="flex min-w-[170px] items-center justify-end gap-2.5">
        <ThemeModeToggle />
        <ThemeColorPicker />
      </div>
    </header>
  )
}
