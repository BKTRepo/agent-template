// ---- Document ----
export type DocumentStatus =
  | 'queued'
  | 'deleting'
  | 'splitting'
  | 'pending'
  | 'parsing'
  | 'terminology'
  | 'analyzing'
  | 'chunking'
  | 'embedding'
  | 'complete'
  | 'failed'

export interface Document {
  id: string
  filename: string
  status: DocumentStatus
  summary: string
  content_length: number | null
  chunks_count: number | null
  total_parts: number
  completed_parts: number
  terminology_total_batches: number
  terminology_completed_batches: number
  chunks_file: string
  input_path: string
  created_at: string
  updated_at: string
  parse_start_time: string
  parse_end_time: string
  parse_duration: number | null
  term_start_time: string
  term_end_time: string
  analyze_start_time: string
  analyze_end_time: string
  analyzing_stage_skipped: boolean
  chunk_start_time: string
  chunk_end_time: string
  embed_start_time: string
  embed_end_time: string
  process_end_time: string
  error_msg: string
  error_trace: string
  /** 上传文件内容 SHA256（增量更新"文件未变化"检测用; 历史文档未回填时为空串） */
  file_sha256: string
  /** 增量更新进行中（期间问答仍使用旧版本向量） */
  is_updating: boolean
  /** 增量更新历史（每次成功更新追加一条; 从未更新过为空数组） */
  update_history: UpdateHistoryEntry[]
  /** 是否可回滚到上一版本（更新失败且上一版本产物齐全时为 true） */
  rollback_available: boolean
  deleting_retry_count?: number
  deletion_retryable?: boolean
  deletion_error_type?: string | null
}

/** 单次增量更新历史记录 */
export interface UpdateHistoryEntry {
  /** 更新完成时间 */
  time: string
  /** 更新所用文件名 */
  filename: string
  /** 复用上一版本的向量数（不可知时为 null, 如嵌入中断续跑） */
  reused: number | null
  /** 新嵌入的向量数（不可知时为 null） */
  embedded: number | null
}

/** 单文档状态详情（轮询接口返回, 与列表条目同构） */
export type DocStatusResponse = Document

/** 文档 Markdown 全文（按需读取产物目录 md 文件） */
export interface DocMarkdownResponse {
  job_id: string
  markdown: string
}

/** 文档术语对照表（按需读取产物目录 terminology.md, 术语提取失败/跳过时为空串） */
export interface DocTerminologyResponse {
  job_id: string
  terminology: string
}

/** 单个入库分块 */
export interface DocChunk {
  id: string
  /** 分块在文档中的顺序 */
  order: number
  /** 分块类型: 文本 / 图片描述 / 表格 / 表格行 */
  modality: 'text' | 'image' | 'table' | 'table_row'
  tokens: number
  content: string
}

/** 文档入库分块列表 */
export interface DocChunksResponse {
  job_id: string
  total: number
  chunks: DocChunk[]
}

// ---- Health ----
export interface HealthResponse {
  status: string
  docling: {
    engine: string
    offline: boolean
    artifacts_path: string | null
  }
}

// ---- Convert ----
export interface ConvertResponse {
  job_id: string
  status: string
  filename: string
  page_count: number
  parts: number
}

/** 增量更新提交响应: 在转换响应基础上增加"文件未变化"标记 */
export type UpdateResponse = ConvertResponse & {
  /** true = 新文件内容与现有版本一致, 已跳过更新（不重新处理） */
  unchanged: boolean
}

// ---- Pipeline ----
export interface PipelineStatus {
  busy: boolean
  job_name: string
  job_start: string | null
  docs: number
  batchs: number
  cur_batch: number
  part_total: number
  part_done: number
  request_pending: boolean
  cancellation_requested: boolean
  latest_message: string
  history_messages: string[]
}

export interface PipelineCancelResponse {
  status: string
  message: string
}

// ---- Files ----
export interface DeleteFilesResponse {
  /** 已派发后台删除任务，不表示磁盘和向量已清理完成。 */
  queued?: string[]
  deleted: string[]
  failed: string[]
}

// ---- Query ----
export interface QueryRequest {
  query: string
  mode: 'naive' | 'hybrid' | 'bypass'
  /** 指定 LLM 模型（后端暂未支持时忽略） */
  model?: string
  response_type: string
  /** 向量检索(naive 模式)稠密检索条数 */
  chunk_top_k: number
  /** 混合检索(hybrid 模式) RRF 融合保留条数（重排候选池） */
  rrf_top_k: number
  dense_top_k?: number | null
  bm25_top_k?: number | null
  conversation_history: { role: string; content: string }[]
  conversation_id?: number | null
  /** 重新生成: 复用会话中该下标的 assistant 消息槽位（需同时传 conversation_id） */
  replace_message_index?: number | null
  enable_rerank: boolean
  include_references: boolean
  temperature?: number | null
}

export interface QueryResponseData {
  response: string
  references: Reference[] | null
  retrieval: RetrievalDetail | null
  /** 本轮用户提问在会话中的下标（未持久化时为 null） */
  user_message_index?: number | null
  /** 本轮回答在会话中的下标（未持久化时为 null） */
  message_index?: number | null
}

export interface Reference {
  reference_id?: string
  file_path?: string
  file_name?: string
  content?: string
  score?: number
}

/** 单个召回分块（列表顺序即当前排名：开重排=重排序，否则 RRF 融合序） */
export interface RetrievalChunk {
  id: string
  content: string
  full_content: string     // 完整内容（展开时使用）
  score: number            // 召回/融合分数（RRF 或 BM25）
  rerank_score?: number    // 重排分数；开启重排且成功时存在，展示时优先于 score
  source: string           // "dense" | "bm25" | 两者
  modality: string         // "text" | "table" | "table_row"
  file_name: string
  reference_id: string
  order: number
}

/** 检索详情: 改写查询 + 召回分块排名列表 */
export interface RetrievalDetail {
  rewritten_query: string | null
  query_mode: string
  total_found: number
  final_count: number
  chunks: RetrievalChunk[]
}

export interface SSEEvent {
  type: 'retrieval' | 'references' | 'content' | 'done' | 'persisted' | 'error' | 'no_active_stream'
  rewritten_query?: string | null
  query_mode?: string
  total_found?: number
  final_count?: number
  chunks?: RetrievalChunk[]
  references?: Reference[]
  content?: string
  /** persisted 事件: 本轮提问/回答在服务端会话中的下标 */
  user_index?: number | null
  assistant_index?: number | null
  /** done 事件携带服务端落盘的思考耗时（重连重建消息时据此展示） */
  thinking_ms?: number | null
}

// ---- Models ----
export interface ModelsResponse {
  model: string
  vector_store: Record<string, unknown>
}

// ---- Conversation ----
export interface Conversation {
  id: number
  title: string
  pinned: boolean
  created_time: string
  updated_time: string
  /** 最近一次提问时间（最后一条用户消息的创建时间, 无则回退会话创建时间） */
  last_question_time?: string
  /** 会话内是否存在生成中的消息（后端据此聚合, 侧栏展示"生成中"标记） */
  generating?: boolean
}

/** 会话内容搜索的单条命中记录 */
export interface ConversationSearchMatch {
  conversation_id: number
  conversation_title: string
  /** 命中消息的角色: user=提问, assistant=AI 回答 */
  role: 'user' | 'assistant'
  /** 命中消息在会话中的下标（点击后跳转定位用） */
  message_index: number
  /** 以命中位置为中心的内容片段（提问或回答） */
  content: string
  /** 命中消息自身的时间（提问=提问时间, 回答=回答时间） */
  created_time: string
}

/** 回答采纳状态（由后端反馈快照接口返回） */
export interface AnswerFeedbackStatus {
  feedback_uid?: string | null
  conversation_id: number
  message_seq: number
  action: 'accepted' | 'revoked' | null
  effective: boolean
  index_status?: 'pending' | 'synced' | 'failed' | 'deleted' | null
  updated_time?: string | null
}

export type MessageStatus = 'done' | 'generating' | 'interrupted'

export interface ConversationMessage {
  role: 'user' | 'assistant'
  content: string
  status?: MessageStatus
  created_time?: string
  /** 思考耗时（毫秒）: 生成时检索+LLM 到首个正文的时间; 旧消息无此字段 */
  thinking_ms?: number | null
  /** 该轮回答的检索详情（持久化, 历史回看可见） */
  retrieval?: RetrievalDetail | null
}
