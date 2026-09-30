import { useEffect, useState } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { getThemeColor } from '@/lib/theme'

const MEDIA = '(prefers-color-scheme: dark)'

/**
 * 主题 Hook：
 *  - themeMode 为 light/dark/system；system 时跟随操作系统 prefers-color-scheme。
 *  - 在 <html> 上切换 .light / .dark 类（HeroUI 主题变量随 .dark 自动切换）。
 *  - 通过覆盖 --accent / --accent-rgb 应用主题色；accent-hover/soft/focus 等
 *    派生色由构建管线预转的 rgb(var(--accent-rgb) / N%) 回退自动跟随。
 */
export function useTheme() {
  const themeMode = useSettingsStore.use.themeMode()
  const setThemeMode = useSettingsStore.use.setThemeMode()
  const accentColor = useSettingsStore.use.accentColor()
  const setAccentColor = useSettingsStore.use.setAccentColor()

  const [systemDark, setSystemDark] = useState<boolean>(() =>
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia(MEDIA).matches
      : false,
  )

  // 监听系统明暗变化（仅 system 模式生效，但始终监听以便切换时即时生效）
  useEffect(() => {
    if (!window.matchMedia) return
    const mq = window.matchMedia(MEDIA)
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    setSystemDark(mq.matches)
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [])

  const resolvedTheme: 'light' | 'dark' =
    themeMode === 'system' ? (systemDark ? 'dark' : 'light') : themeMode

  // 应用明暗类
  useEffect(() => {
    const root = window.document.documentElement
    root.classList.remove('light', 'dark')
    root.classList.add(resolvedTheme)
  }, [resolvedTheme])

  // 应用主题色（--accent + --accent-rgb 三值），派生色自动跟随;
  // --accent-rgb 供旧浏览器的 rgb(var(--accent-rgb) / N%) 混色回退使用
  useEffect(() => {
    const root = window.document.documentElement
    const color = getThemeColor(accentColor)
    root.style.setProperty('--accent', color.accent)
    root.style.setProperty('--accent-rgb', color.rgb)
  }, [accentColor])

  return { themeMode, setThemeMode, resolvedTheme, accentColor, setAccentColor }
}
