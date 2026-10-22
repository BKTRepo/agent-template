import type { ReactNode } from 'react'
import { toast as herouiToast } from '@heroui/react'

/** toast 默认展示时长（毫秒）: 组件库默认 4000, 项目内统一缩短为 1s */
const TOAST_TIMEOUT = 1000

type ToastOptions = Parameters<typeof herouiToast.success>[1]

function withDefaults(options?: ToastOptions): ToastOptions {
  return { timeout: TOAST_TIMEOUT, ...options }
}

/**
 * 统一 toast 出口: 全站提示默认 1 秒自动消失。
 * 需要更长展示时间或常驻时, 调用方可通过 options.timeout 覆盖（0 = 不自动关闭）。
 */
export const toast = {
  success: (message: ReactNode, options?: ToastOptions) => herouiToast.success(message, withDefaults(options)),
  danger: (message: ReactNode, options?: ToastOptions) => herouiToast.danger(message, withDefaults(options)),
  info: (message: ReactNode, options?: ToastOptions) => herouiToast.info(message, withDefaults(options)),
  warning: (message: ReactNode, options?: ToastOptions) => herouiToast.warning(message, withDefaults(options)),
}
