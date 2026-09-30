export const POLL_INTERVAL = 2000 // 2s between status polls
export const HEALTH_POLL_INTERVAL = 30000 // 30s between health checks
export const MAX_CONVERSATION_HISTORY = 20
export const API_BASE = "/api"

/** 可选 LLM 模型列表（对话输入区切换） */
export const LLM_MODELS = ['kimi-for-coding', 'deepseek-v4-flash', 'deepseek-v4-flash-0731-think', 'glm-51-local']
// 空值表示使用后端配置，避免首次访问将旧环境的模型名发给新服务。
export const DEFAULT_LLM_MODEL = ''

/** 检索模式选项（仅中文文案, id 与后端 mode 对应） */
export const CHAT_MODES: { id: 'hybrid' | 'naive' | 'bypass'; label: string; desc: string }[] = [
  { id: 'hybrid', label: '混合检索', desc: '向量 + 关键词双路召回融合' },
  { id: 'naive', label: '向量检索', desc: '仅语义向量召回' },
  { id: 'bypass', label: '直接问答', desc: '不检索知识库' },
]
