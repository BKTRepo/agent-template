import type { ReactNode } from 'react'
import { Checkbox, CheckboxContent, CheckboxControl, CheckboxIndicator } from '@heroui/react'
import { cn } from '@/lib/utils'

interface Props {
  isSelected: boolean
  /** react-aria 约定: 回调参数为新的选中态 */
  onChange: (isSelected: boolean) => void
  /** 可选文字标签; 不传则为纯选择框（如表格行选择） */
  children?: ReactNode
  className?: string
  isDisabled?: boolean
}

/** 复选框封装——收敛 HeroUI v3 的组合式结构, 页面侧按原生 Checkbox 习惯使用 */
export function CheckboxField({ isSelected, onChange, children, className, isDisabled }: Props) {
  return (
    <Checkbox
      isSelected={isSelected}
      onChange={onChange}
      isDisabled={isDisabled}
      className={cn(className)}
    >
      <CheckboxContent>
        <CheckboxControl>
          <CheckboxIndicator />
        </CheckboxControl>
        {children}
      </CheckboxContent>
    </Checkbox>
  )
}
