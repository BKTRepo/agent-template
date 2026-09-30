import { ModalTrigger } from '@heroui/react'

/**
 * 受控弹层的 pressable 占位子元素。
 *
 * HeroUI v3 的 Modal/Drawer 根组件内部是 react-aria-components 的 DialogTrigger,
 * 它用 PressResponder 包裹子树, 并要求树内存在一个"可按"后代（ModalTrigger /
 * usePress 注册）, 否则 dev 下每个弹层实例都会打印:
 *   "A PressResponder was rendered without a pressable child..."
 *
 * 本项目的弹窗/抽屉全部由 isOpen / state 受控打开, 打开按钮位于外层页面工具栏,
 * 弹层组件树内没有（也不应有）触发器子元素, 因此必然触发该警告。
 * 这里补一个视觉隐藏、不可 Tab 聚焦的 pressable 元素满足注册约定:
 * - 仅用于让 PressResponder 完成 register(), 不参与任何交互（display 隐藏之外
 *   额外 tabIndex={-1} + aria-hidden, 键盘与读屏均不可达）;
 * - 警告本身只在 dev 构建存在（生产产物中该分支被剥离）, 此组件在生产环境
 *   除了一个隐藏 DOM 节点外无任何副作用。
 *
 * 注意必须用 sr-only 而非 display:none —— Pressable 的 dev 校验会跳过
 * isDisabled 之外"不可见/不可聚焦"的子元素并另行告警。
 */
export function OverlayPressTarget() {
  return <ModalTrigger aria-hidden="true" tabIndex={-1} className="sr-only" />
}
