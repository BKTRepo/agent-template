import { useEffect, useState } from 'react'
import { RotateCcw, Settings2 } from 'lucide-react'
import {
  Button, Input,
  Select, SelectTrigger, SelectValue, SelectPopover,
  ListBox, ListBoxItem,
} from '@heroui/react'
import { AppModal } from '@/components/common/Modal'
import { SwitchField } from '@/components/common/SwitchField'
import { useSettingsStore } from '@/stores/settingsStore'
import { CHAT_MODES } from '@/lib/constants'

const RESPONSE_TYPES = ['多段落', '单段落', '要点列表']

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

interface Props {
  open: boolean
  onClose: () => void
}

/**
 * 问答参数设置弹窗: 检索模式 + 各模式对应参数 + 流式开关。
 * 混合检索展示三个 TopK, 向量检索仅一个 TopK, 直接问答无检索参数。
 * 所有修改即时保存到 settingsStore（persist 持久化）。
 */
export function ChatSettingsDialog({ open, onClose }: Props) {
  const chatMode = useSettingsStore.use.chatMode()
  const setChatMode = useSettingsStore.use.setChatMode()
  const streamEnabled = useSettingsStore.use.streamEnabled()
  const setStreamEnabled = useSettingsStore.use.setStreamEnabled()
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
  const temperature = useSettingsStore.use.temperature()
  const setTemperature = useSettingsStore.use.setTemperature()
  const resetAllSettings = useSettingsStore.use.resetAllSettings()

  return (
    <AppModal
      open={open}
      onClose={onClose}
      size="md"
      scroll="inside"
      title={
        <span className="flex items-center gap-2">
          <Settings2 className="size-4 text-muted" />
          问答参数设置
        </span>
      }
      description="参数修改即时保存"
      footer={
        <>
          <Button variant="outline" onPress={resetAllSettings}>
            <RotateCcw className="size-4" /> 重置默认
          </Button>
          <Button variant="primary" onPress={onClose}>完成</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {/* 检索模式 */}
        <div className="space-y-1.5">
          <span className="text-xs text-muted">检索模式</span>
          <Select
            selectedKey={chatMode}
            onSelectionChange={(k) => setChatMode(k as 'naive' | 'hybrid' | 'bypass')}
            aria-label="检索模式"
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectPopover>
              <ListBox>
                {CHAT_MODES.map((m) => (
                  <ListBoxItem key={m.id} id={m.id}>{m.label}</ListBoxItem>
                ))}
              </ListBox>
            </SelectPopover>
          </Select>
        </div>

        {/* 混合检索: 三个 Top-K */}
        {chatMode === 'hybrid' && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <span className="text-xs text-muted">向量检索 Top K</span>
              <div className="flex items-center gap-1">
                <TopKField value={denseTopK} onChange={setDenseTopK} />
                <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setDenseTopK(100)}>
                  <RotateCcw className="size-3" />
                </Button>
              </div>
            </div>
            <div className="space-y-1.5">
              <span className="text-xs text-muted">BM25 关键词 Top K</span>
              <div className="flex items-center gap-1">
                <TopKField value={bm25TopK} onChange={setBm25TopK} />
                <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setBm25TopK(100)}>
                  <RotateCcw className="size-3" />
                </Button>
              </div>
            </div>
            <div className="space-y-1.5">
              <span className="text-xs text-muted">RRF 合并 Top K</span>
              <div className="flex items-center gap-1">
                <TopKField value={rrfTopK} onChange={setRrfTopK} />
                <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setRrfTopK(100)}>
                  <RotateCcw className="size-3" />
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* 向量检索: 单个 Top-K */}
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
            <Button variant="ghost" size="sm" isIconOnly className="size-6 shrink-0" onPress={() => setTemperature(0.7)}>
              <RotateCcw className="size-3" />
            </Button>
          </div>
          <div className="flex justify-between text-[10px] text-muted/60">
            <span>精确</span><span>平衡</span><span>创造</span>
          </div>
        </div>

        {/* 开关选项 */}
        <div className="space-y-2.5 rounded-xl bg-default/40 p-3">
          <SwitchField isSelected={streamEnabled} onChange={setStreamEnabled}>流式响应</SwitchField>
          {chatMode !== 'bypass' && (
            <SwitchField isSelected={enableRerank} onChange={setEnableRerank}>启用重排序</SwitchField>
          )}
          {chatMode !== 'bypass' && (
            <SwitchField isSelected={includeRefs} onChange={setIncludeRefs}>包含参考文献</SwitchField>
          )}
        </div>
      </div>
    </AppModal>
  )
}
