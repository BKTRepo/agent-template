import { Spinner } from '@heroui/react'
import { cn } from '@/lib/utils'

export function LoadingSpinner({ className }: { className?: string }) {
  return (
    <div className={cn('flex items-center justify-center p-10', className)}>
      <Spinner size="lg" color="accent" />
    </div>
  )
}
