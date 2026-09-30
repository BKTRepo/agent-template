import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { Button } from '@heroui/react'
import { copyText } from '@/lib/clipboard'

export function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    if (!(await copyText(text))) return
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      isIconOnly
      className={`size-6 ${className ?? ''}`}
      aria-label={copied ? '已复制' : '复制'}
      onPress={handleCopy}
    >
      {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5 text-muted" />}
    </Button>
  )
}
