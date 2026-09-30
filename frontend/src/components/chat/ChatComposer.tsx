import { forwardRef, useCallback, useEffect, useRef } from 'react'
import { ArrowUp, ChevronDown, Cpu, Search, Square } from 'lucide-react'
import {
  Button, TextArea,
  Dropdown, DropdownTrigger, DropdownPopover, DropdownMenu, DropdownItem,
  buttonVariants,
} from '@heroui/react'
import { useSettingsStore } from '@/stores/settingsStore'
import { LLM_MODELS, CHAT_MODES } from '@/lib/constants'
import { cn } from '@/lib/utils'

/** 输入框最大高度（px）, 与 className 的 max-h 保持一致; 超过后内部滚动 */
const MAX_INPUT_HEIGHT = 160

interface Props {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  onStop: () => void
  /** 是否正在流式接收（显示停止按钮） */
  isStreaming: boolean
  /** 存在生成中的消息（禁用输入） */
  busy: boolean
  onKeyDown: (e: React.KeyboardEvent) => void
}

/**
 * 对话输入区: 圆角输入框 + 底部工具栏。
 * 左下角选择 LLM 模型, 右侧为「流式/非流式」滑块标签与发送按钮。
 */
export const ChatComposer = forwardRef<HTMLTextAreaElement, Props>(function ChatComposer(
  { value, onChange, onSend, onStop, isStreaming, busy, onKeyDown },
  ref,
) {
  const llmModel = useSettingsStore.use.llmModel()
  const setLlmModel = useSettingsStore.use.setLlmModel()
  const chatMode = useSettingsStore.use.chatMode()
  const setChatMode = useSettingsStore.use.setChatMode()

  const modeLabel = CHAT_MODES.find((m) => m.id === chatMode)?.label ?? '混合检索'

  // 输入框高度随内容自适应: 内容变多时向上撑开（封顶 MAX_INPUT_HEIGHT）, 清空后回落
  const innerRef = useRef<HTMLTextAreaElement | null>(null)
  const assignRef = useCallback((el: HTMLTextAreaElement | null) => {
    innerRef.current = el
    if (typeof ref === 'function') ref(el)
    else if (ref) (ref as React.MutableRefObject<HTMLTextAreaElement | null>).current = el
  }, [ref])

  useEffect(() => {
    const el = innerRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_INPUT_HEIGHT)}px`
  }, [value])

  return (
    <div className="chat-composer shrink-0 rounded-2xl border border-border bg-surface p-2 shadow-[0_2px_6px_rgb(0_0_0/0.1)] transition-[border-color,box-shadow] duration-300 focus-within:border-accent/50 focus-within:shadow-[0_2px_6px_rgb(0_0_0/0.1),0_0_14px_color-mix(in_oklab,var(--accent)_25%,transparent),0_0_30px_color-mix(in_oklab,var(--accent)_14%,transparent),0_0_60px_color-mix(in_oklab,var(--accent)_7%,transparent)]">
      <TextArea
        ref={assignRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="输入你的问题…（Enter 发送，Shift+Enter 换行）"
        className="max-h-[160px] min-h-[56px] w-full resize-none border-0 bg-surface px-2 py-1 text-sm shadow-none"
        disabled={busy}
      />

      {/* 底部工具栏: 与输入框同在一个容器内, 视觉一体 */}
      <div className="flex items-center justify-between gap-2 px-1">
        {/* 左下: 检索模式 + LLM 模型选择 */}
        <div className="flex min-w-0 items-center gap-1">
          <Dropdown>
            {/* DropdownTrigger 自身即 RAC <button>, 内部不可再嵌 Button（button 套 button
                为非法 HTML, 且触发 react-aria PressResponder 警告）; 用 buttonVariants
                直接为 trigger 应用按钮样式。
                注: dropdown__trigger 的 display:inline-block 与 .button 的 inline-flex
                同优先级且源码序更靠后, 会覆盖 flex 布局导致内容换行, 故显式追加
                inline-flex/items-center 工具类（utilities 层优先级更高）强制单行 flex。 */}
            <DropdownTrigger
              aria-label="选择检索模式"
              className={cn(
                buttonVariants({ variant: 'ghost', size: 'sm' }),
                'inline-flex h-7 max-w-[160px] items-center gap-1.5 px-2 text-xs text-muted',
              )}
            >
              <Search className="size-3.5 shrink-0" />
              <span className="min-w-0 truncate">{modeLabel}</span>
              <ChevronDown className="size-3 shrink-0" />
            </DropdownTrigger>
            <DropdownPopover placement="top start" className="min-w-[180px]">
              <DropdownMenu
                aria-label="检索模式"
                selectionMode="single"
                selectedKeys={[chatMode]}
                onAction={(key) => setChatMode(key as 'hybrid' | 'naive' | 'bypass')}
              >
                {CHAT_MODES.map((m) => (
                  <DropdownItem key={m.id} id={m.id} textValue={m.label}>
                    <span className="flex flex-col gap-0.5">
                      <span>{m.label}</span>
                      <span className="text-xs font-normal text-muted">{m.desc}</span>
                    </span>
                  </DropdownItem>
                ))}
              </DropdownMenu>
            </DropdownPopover>
          </Dropdown>

          <Dropdown>
            <DropdownTrigger
              aria-label="选择 LLM 模型"
              className={cn(
                buttonVariants({ variant: 'ghost', size: 'sm' }),
                'inline-flex h-7 max-w-[220px] items-center gap-1.5 px-2 text-xs text-muted',
              )}
            >
              <Cpu className="size-3.5 shrink-0" />
              <span className="min-w-0 truncate">{llmModel}</span>
              <ChevronDown className="size-3 shrink-0" />
            </DropdownTrigger>
            <DropdownPopover placement="top start" className="min-w-[200px]">
              <DropdownMenu
                aria-label="LLM 模型"
                selectionMode="single"
                selectedKeys={[llmModel]}
                onAction={(key) => setLlmModel(String(key))}
              >
                {LLM_MODELS.map((m) => (
                  <DropdownItem key={m} id={m}>{m}</DropdownItem>
                ))}
              </DropdownMenu>
            </DropdownPopover>
          </Dropdown>
        </div>

        {/* 右侧: 发送 */}
        <div className="flex items-center gap-2">
          {isStreaming ? (
            <Button
              variant="danger"
              size="sm"
              isIconOnly
              className="size-8 rounded-full"
              onPress={onStop}
              aria-label="停止生成"
            >
              <Square className="size-3.5" />
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              isIconOnly
              className="size-8 rounded-full"
              onPress={onSend}
              isDisabled={busy || !value.trim()}
              aria-label="发送"
            >
              <ArrowUp className="size-3.5" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
})
