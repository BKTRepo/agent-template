/**
 * 主题配置——全部为本地 CSS 颜色值（hex）, 无任何外链资源, 保证离线可用。
 *
 * 兼容说明（Chrome/Edge 99~110 离线环境）:
 * - accent 以 hex 表示（旧浏览器不支持 oklch）; rgb 为对应的「r g b」三值,
 *   由 useTheme 写入 --accent-rgb, 供 CSS 中 `rgb(var(--accent-rgb) / N%)`
 *   形式的透明度混色回退使用（替代旧浏览器不支持的 color-mix）。
 * - HeroUI v3 的 accent 派生色（accent-hover / accent-soft / focus 等）由
 *   构建管线把 color-mix(var(--accent) ...) 预转为上述 rgb 三值回退写法,
 *   因此切换主题色时只需覆盖 --accent / --accent-rgb 两个变量。
 */

export type ThemeMode = 'light' | 'dark' | 'system'

export interface ThemeColor {
  key: string
  label: string
  /** 主色（accent）, hex 表示 */
  accent: string
  /** 主色的 "r g b" 三值, 写入 --accent-rgb */
  rgb: string
}

/** 可选主题色预设（hex 由原 oklch 值换算而来） */
export const THEME_COLORS: ThemeColor[] = [
  { key: 'blue', label: '蓝色', accent: '#1d84f5', rgb: '29 132 245' },
  { key: 'violet', label: '紫色', accent: '#815ae4', rgb: '129 90 228' },
  { key: 'pink', label: '粉色', accent: '#d84497', rgb: '216 68 151' },
  { key: 'red', label: '红色', accent: '#e23439', rgb: '226 52 57' },
  { key: 'orange', label: '橙色', accent: '#e57600', rgb: '229 118 0' },
  { key: 'green', label: '绿色', accent: '#20a04e', rgb: '32 160 78' },
  { key: 'cyan', label: '青色', accent: '#00a5be', rgb: '0 165 190' },
  { key: 'black', label: '黑色', accent: '#191924', rgb: '25 25 36' },
]

export const DEFAULT_THEME_COLOR = 'blue'

export function getThemeColor(key: string): ThemeColor {
  return THEME_COLORS.find((c) => c.key === key) ?? THEME_COLORS[0]!
}
