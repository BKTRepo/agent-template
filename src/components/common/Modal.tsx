import type { ReactNode } from 'react'
import {
  Modal,
  ModalBackdrop,
  ModalContainer,
  ModalDialog,
  ModalHeader,
  ModalHeading,
  ModalBody,
  ModalFooter,
  ModalCloseTrigger,
} from '@heroui/react'
import { OverlayPressTarget } from './OverlayPressTarget'

export type ModalSize = 'xs' | 'sm' | 'md' | 'lg' | 'full'

interface AppModalProps {
  open: boolean
  onClose: () => void
  /** 标题（可传 ReactNode, 如图标 + 文字 + 徽标组合） */
  title: ReactNode
  /** 标题下方的说明文字 */
  description?: ReactNode
  size?: ModalSize
  /** inside: 正文内部滚动; outside: 整个弹窗滚动 */
  scroll?: 'inside' | 'outside'
  /** 点击遮罩 / Esc 是否可关闭 */
  isDismissable?: boolean
  /** 隐藏右上角关闭按钮 */
  hideClose?: boolean
  /** 透传给弹窗面板（ModalDialog）的样式, 可用于覆盖宽度等 */
  dialogClassName?: string
  children: ReactNode
  footer?: ReactNode
}

/**
 * 受控 Modal 封装——统一 HeroUI v3 的组合式结构
 * (Modal > ModalBackdrop > ModalContainer > ModalDialog > Header/Body/Footer)，
 * 各业务弹窗复用, 行为与原 Radix Dialog 的 open/onClose 受控模式保持一致。
 */
export function AppModal({
  open,
  onClose,
  title,
  description,
  size = 'md',
  scroll,
  isDismissable = true,
  hideClose = false,
  dialogClassName,
  children,
  footer,
}: AppModalProps) {
  return (
    <Modal
      isOpen={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) onClose()
      }}
    >
      {/* 受控弹层无触发器子元素, 补一个隐藏 pressable 避免 react-aria dev 警告 */}
      <OverlayPressTarget />
      <ModalBackdrop isDismissable={isDismissable}>
        <ModalContainer size={size} scroll={scroll}>
          <ModalDialog className={dialogClassName}>
            <ModalHeader>
              <ModalHeading>{title}</ModalHeading>
              {description ? (
                <p className="text-sm text-muted">{description}</p>
              ) : null}
              {!hideClose && <ModalCloseTrigger />}
            </ModalHeader>
            <ModalBody>{children}</ModalBody>
            {footer ? <ModalFooter>{footer}</ModalFooter> : null}
          </ModalDialog>
        </ModalContainer>
      </ModalBackdrop>
    </Modal>
  )
}
