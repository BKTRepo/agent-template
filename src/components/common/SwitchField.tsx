import type { ReactNode } from 'react'
import { Switch, SwitchContent, SwitchControl, SwitchThumb } from '@heroui/react'

interface Props {
  isSelected: boolean
  onChange: (isSelected: boolean) => void
  children?: ReactNode
  size?: 'sm' | 'md' | 'lg'
  isDisabled?: boolean
}

/** 开关封装——收敛 HeroUI v3 的组合式结构 */
export function SwitchField({ isSelected, onChange, children, size = 'sm', isDisabled }: Props) {
  return (
    <Switch isSelected={isSelected} onChange={onChange} size={size} isDisabled={isDisabled}>
      <SwitchContent>
        <SwitchControl>
          <SwitchThumb />
        </SwitchControl>
        {children}
      </SwitchContent>
    </Switch>
  )
}
