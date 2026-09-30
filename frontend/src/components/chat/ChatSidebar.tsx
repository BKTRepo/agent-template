import { useEffect, useState } from 'react'
import { RotateCcw, ChevronLeft, ChevronRight, Settings2 } from 'lucide-react'
import {
  Button, Input,
  Select, SelectTrigger, SelectValue, SelectPopover,
  ListBox, ListBoxItem,
} from '@heroui/react'
import { SwitchField } from '@/components/common/SwitchField'
import { useSettingsStore } from '@/stores/settingsStore'

const RESPONSE_TYPES = ['多段落', '单段落', '要点列表']

const MODE_OPTIONS = [
  { id: 'hybrid', label: 'Hybrid (混合检索)' },
  { id: 'naive', label: 'Naive (向量检索)' },
  { id: 'bypass', label: 'Bypass (直接LLM)' },
]

/** Top-K 数字输入框: 允许直接输入数值, 失焦时还原非法值, 外部变化时同步 */
function TopKField({ value, onChange, min = 1, max = 500 }: {
  value: number
  onChange: (n: number) => void
  min?: number
  max?: number
}) {
  const [text, setText] = useState(String(value))
  useEffect(() => {
    setText(String(value))
  }, [value])
  const clamp = (n: number) => Math.max(min, Math.min(max, n))
  return (
    <Input
      type="number"
      min={min}
      max={max}
      value={text}
      onChange={(e) => {
        setText(e.target.value)
        const n = parseInt(e.target.value, 10)
        if (!Number.isNaN(n)) onChange(clamp(n))
      }}
      onBlur={() => setText(String(value))}
      className="h-8 flex-1 text-xs"
    />
  )
}

export function ChatSidebar() {
  const [expanded, setExpanded] = useState(false)

  const chatMode = useSettingsStore.use.chatMode()
  const setChatMode = useSettingsStore.use.setChatMode()
  const naiveTopK = useSettingsStore.use.naiveTopK()
  const setNaiveTopK = useSettingsStore.use.setNaiveTopK()
  const rrfTopK = useSettingsStore.use.rrfTopK()
  const setRrfTopK = useSettingsStore.use.setRrfTopK()
  const denseTopK = useSettingsStore.use.denseTopK()
  const setDenseTopK = useSettingsStore.use.setDenseTopK()
  const bm25TopK = useSettingsStore.use.bm25TopK()
  const setBm25TopK = useSettingsStore.use.setBm25TopK()
  const responseType = useSettingsStore.use.responseType()
  const setResponseType = useSettingsStore.use.setResponseType()
  const enableRerank = useSettingsStore.use.enableRerank()
  const setEnableRerank = useSettingsStore.use.setEnableRerank()
  const includeRefs = useSettingsStore.use.includeRefs()
  const setIncludeRefs = useSettingsStore.use.setIncludeRefs()
  const streamEnabled = useSettingsStore.use.streamEnabled()
  const setStreamEnabled = useSettingsStore.use.setStreamEnabled()
  const temperature = useSettingsStore.use.temperature()
  const setTemperature = useSettingsStore.use.setTemperature()
  const resetAllSettings = useSettingsStore.use.resetAllSettings()

  return (
    <div className="relative flex shrink-0">
      {/* 收起态窄条 */}
      {!expanded && (
        <div
          className="flex w-10 cursor-pointer select-none flex-col items-center gap-3 border-l border-border bg-surface py-4"
          onClick={() => setExpanded(true)}
          title="展开查询设置"
        >
          <ChevronLeft className="size-4 text-muted" />
          <Settings2 className="size-4 text-muted" />
          <span className="vertical-text text-[10px] text-muted">查询设置</span>
        </div>
      )}

      {expanded && (
        <div className="flex w-[280px] shrink-0 flex-col border-l border-border bg-surface">
          <div className="px-4 pb-2 pt-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Button variant="ghost" size="sm" isIconOnly className="size-6" onPress={() => setExpanded(false)}>
                  <ChevronRight className="size-3.5" />
                </Button>
                <div>
                  <h4 className="text-sm font-semibold text-foreground">查询设置</h4>
                  <p className="text-xs text-muted">配置参数，优化效果</p>
                </div>
              </div>
              <Button variant="ghost" size="sm" className="text-xs" onPress={resetAllSettings}>
                <RotateCcw className="mr-1 h-3 w-3" /> 重置
              </Button>
            </div>
          </div>

          <div className="flex flex-col gap-4 overflow-auto px-4 pb-4">
            {/* 检索模式 */}
            <div className="space-y-1.5">
              <span className="text-xs text-muted">检索模式</span>
              <div className="flex items-center gap-1">
                <Select
                  selectedKey={chatMode}
                  onSelectionChange={(k) => setChatMode(k as 'naive' | 'hybrid' | 'bypass')}
                  aria-label="检索模式"
                  className="flex-1"
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectPopover>
                    <ListBox>
                      {MODE_OPTIONS.map((o) => (
                        <ListBoxItem key={o.id} id={o.id}>{o.label}</ListBoxItem>
                      ))}
                    </ListBox>
                  </SelectPopover>
                </Select>
                <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setChatMode('hybrid')}>
                  <RotateCcw className="size-3" />
                </Button>
              </div>
            </div>

            {/* naive 模式: 单 Top K */}
            {chatMode === 'naive' && (
              <div className="space-y-1.5">
                <span className="text-xs text-muted">Top K</span>
                <div className="flex items-center gap-1">
                  <TopKField value={naiveTopK} onChange={setNaiveTopK} />
                  <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setNaiveTopK(100)}>
                    <RotateCcw className="size-3" />
                  </Button>
                </div>
              </div>
            )}

            {/* hybrid 模式: 三个 Top-K */}
            {chatMode === 'hybrid' && (
              <>
                <div className="space-y-1.5">
                  <span className="text-xs text-muted">向量检索Top K</span>
                  <div className="flex items-center gap-1">
                    <TopKField value={denseTopK} onChange={setDenseTopK} />
                    <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setDenseTopK(100)}>
                      <RotateCcw className="size-3" />
                    </Button>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <span className="text-xs text-muted">BM25关键词检索Top K</span>
                  <div className="flex items-center gap-1">
                    <TopKField value={bm25TopK} onChange={setBm25TopK} />
                    <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setBm25TopK(100)}>
                      <RotateCcw className="size-3" />
                    </Button>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <span className="text-xs text-muted">RRF合并Top K</span>
                  <div className="flex items-center gap-1">
                    <TopKField value={rrfTopK} onChange={setRrfTopK} />
                    <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setRrfTopK(100)}>
                      <RotateCcw className="size-3" />
                    </Button>
                  </div>
                </div>
              </>
            )}

            {/* 回答格式 */}
            <div className="space-y-1.5">
              <span className="text-xs text-muted">回答格式</span>
              <div className="flex items-center gap-1">
                <Select
                  selectedKey={responseType}
                  onSelectionChange={(k) => setResponseType(String(k))}
                  aria-label="回答格式"
                  className="flex-1"
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectPopover>
                    <ListBox>
                      {RESPONSE_TYPES.map((t) => (
                        <ListBoxItem key={t} id={t}>{t}</ListBoxItem>
                      ))}
                    </ListBox>
                  </SelectPopover>
                </Select>
                <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setResponseType('多段落')}>
                  <RotateCcw className="size-3" />
                </Button>
              </div>
            </div>

            {/* 温度 */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted">温度</span>
                <span className="font-mono text-xs tabular-nums text-foreground">{temperature.toFixed(1)}</span>
              </div>
              <div className="flex items-center gap-1">
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-default accent-(--accent)"
                />
                <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setTemperature(0.1)}>
                  <RotateCcw className="size-3" />
                </Button>
              </div>
              <div className="flex justify-between text-[10px] text-muted/60">
                <span>精确</span><span>平衡</span><span>创造</span>
              </div>
            </div>

            {/* 开关选项 */}
            <div className="space-y-2.5">
              {(chatMode === 'naive' || chatMode === 'hybrid') && (
                <SwitchField isSelected={enableRerank} onChange={setEnableRerank}>启用重排</SwitchField>
              )}
              {chatMode !== 'bypass' && (
                <SwitchField isSelected={includeRefs} onChange={setIncludeRefs}>包含引用</SwitchField>
              )}
              <SwitchField isSelected={streamEnabled} onChange={setStreamEnabled}>流式响应</SwitchField>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
