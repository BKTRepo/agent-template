"""Query-only settings; existing model and ingestion settings remain authoritative."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional, List, Dict, Any
from configure import PROJECT_CONFIG as BASE_CONFIG

class QuerySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    ANSWER_CONCISE_RETRY_MAX_CHARS: int = Field(default=1500, ge=200, description="精简重生成提示中的答案篇幅上限")
    ANSWER_PARTIAL_FALLBACK_ENABLED: bool = Field(default=True, description="精简重生成仍截断时是否返回已有部分答案")
    ANSWER_TRUNCATION_RETRY_ENABLED: bool = Field(default=True, description="答案达到 max_tokens 时是否复用同一证据精简重生成一次")
    CHAT_HISTORY_MAX_MESSAGES: int = Field(
            default=20,
            ge=0,
            description=(
                "问答时注入 LLM 的最近历史消息【条数】硬上限（0 = 不注入历史）。"
                "与 CHAT_HISTORY_MAX_TOKENS 共同约束历史窗口, 取更严的一方"
            ),
        )
    CHAT_HISTORY_MAX_TOKENS: int = Field(
            default=6000,
            ge=0,
            description=(
                "问答时注入 LLM 的历史窗口【token】预算（0 = 不注入历史）。"
                "为主约束, 保证历史不挤爆上下文; 条数上限为保险丝。"
                "历史 token 会计入总预算, 剩余才分给检索分块"
            ),
        )
    CHAT_REWRITE_HISTORY_MESSAGES: int = Field(
            default=6,
            ge=0,
            description=(
                "历史感知检索改写（指代消解）参考的最近历史消息条数。"
                "仅多轮时触发, 用最近几轮把当前问题消解为自包含查询再检索"
            ),
        )
    CHAT_SUMMARY_BATCH_MESSAGES: int = Field(
            default=4,
            ge=1,
            description=(
                "被挤出近期窗口、待折叠进滚动摘要的消息达到该条数才触发一次折叠。"
                "批量摊销摘要 LLM 成本（值越大折叠越少、越省）"
            ),
        )
    CHAT_SUMMARY_MAX_TOKENS: int = Field(
            default=500,
            ge=0,
            description=(
                "滚动摘要自身的目标 token 体积（保持精炼）。"
                "摘要作为背景上下文注入 system, 其 token 计入总预算"
            ),
        )
    CHUNK_TOP_K: int = Field(default=100, ge=1, description="向量检索(naive 模式)稠密检索返回的分块条数")
    DOC_BUDGET_MAX_SHARE: float = Field(
            default=0.6,
            ge=0.0,
            le=1.0,
            description=(
                "最终检索窗口中单个文档可占的 token 预算比例上限（多文档联合检索保障）: "
                "多文档分块同时竞争预算时, 防止单一主导文档霸占窗口、挤掉问题涉及的其他文档; "
                "超限分块被暂时跳过, 剩余预算按相关性回填（单文档查询回填后与旧逻辑完全一致）。"
                "1.0 = 关闭封顶"
            ),
        )
    DOC_RECALL_CHUNKS_PER_DOC: int = Field(
            default=8,
            ge=1,
            description="每份命中文档定向注入候选池的分块数上限",
        )
    DOC_RECALL_ENABLED: bool = Field(
            default=True,
            description=(
                "文档级召回总开关（文档摘要索引 + 定向注入）: 查询与文档摘要余弦"
                "匹配命中的文档, 定向召回其 top 分块注入重排候选池。摘要层只保证"
                "涉及文档被认真考虑, 是否进最终窗口仍由重排阈值唯一决定（双闸门）"
            ),
        )
    DOC_RECALL_INDEX_TTL: float = Field(
            default=30.0,
            description=(
                "文档摘要索引新鲜度指纹的 Web 侧缓存 TTL（秒）: TTL 内不核对文档表指纹。"
                "新入库文档最多延迟 TTL 秒进入文档级召回; 设为 0 则每次查询都核对"
            ),
        )
    DOC_RECALL_MAX_DOCS: int = Field(
            default=3,
            ge=1,
            description="单次查询最多定向注入的文档数（按摘要相似度取 top, 控制增量 RPC 与候选池规模）",
        )
    DOC_RECALL_MIN_SCORE: float = Field(
            default=0.5,
            ge=0.0,
            le=1.0,
            description="查询向量与文档摘要向量的余弦相似度阈值, 达标文档判定为问题涉及文档（需 A/B 校准）",
        )
    FIELD_VARIANT_NORMALIZATION_ENABLED: bool = Field(default=True, description="查询侧是否统一 Field/DE/F/域号写法")
    HYBRID_BM25_TOP_K: int = Field(default=60, description="混合检索每路 BM25 检索的候选数（未显式传 bm25_top_k 时生效）")
    HYBRID_DENSE_TOP_K: int = Field(default=60, description="混合检索每路稠密检索的候选数（未显式传 dense_top_k 时生效）")
    MAX_TOTAL_TOKENS: int = Field(default=30000, description="上下文 token 总预算上限")
    QUERY_MEMORY_ENABLED: bool = Field(
            default=True,
            description="是否启用采纳经验查询指导；关闭时直接走全库检索",
        )
    QUERY_MEMORY_GLOBAL_MIN_RATIO: float = Field(
            default=0.30,
            ge=0.0,
            le=1.0,
            description="候选池为全库其他文档预留的最低比例；最终由统一重排决定是否采用",
        )
    QUERY_MEMORY_GUIDED_WEIGHT: float = Field(
            default=1.2,
            ge=1.0,
            description="历史范围候选在融合阶段的 RRF 权重",
        )
    QUERY_MEMORY_MIN_SCORE: float = Field(
            default=0.72,
            ge=-1.0,
            le=1.0,
            description="查询经验余弦相似度最低阈值；低于此值不限定文档范围",
        )
    QUERY_MEMORY_SCOPED_SEARCH_ENABLED: bool = Field(
            default=False,
            description="是否用采纳经验范围加权召回，同时保留全库候选参与统一重排",
        )
    QUERY_MEMORY_SHADOW_MODE: bool = Field(
            default=False,
            description="影子模式：记录采纳经验命中但不使用文档范围限制实际检索",
        )
    QUERY_MEMORY_TOP_K: int = Field(
            default=5,
            ge=1,
            description="查询指导最多召回的采纳经验条数",
        )
    RAG_CONTEXT_TOP_K: int = Field(
            default=20,
            ge=1,
            description="重排后送入生成模型的最大分块数；候选池仍保留较大 top-k 供重排",
        )
    RERANK_BINDING_API_KEY: str = Field(default="", description="Rerank API Key")
    RERANK_BINDING_HOST: str = Field(default="https://api.siliconflow.cn/v1/rerank", description="Rerank API 地址")
    RERANK_ENABLE_CHUNKING: bool = Field(default=True, description="长文档是否切块后再重排")
    RERANK_MAX_TOKENS_PER_DOC: int = Field(default=480, description="重排切块的单块 token 上限")
    RERANK_MIN_SCORE: float = Field(default=0.0, description="重排最低分数阈值")
    RERANK_MODEL: str = Field(default="BAAI/bge-reranker-v2-m3", description="Rerank 模型")
    RERANK_TOP_K: int = Field(default=50, ge=1, description="重排后最多返回的分块数（最终检索窗口, 从候选池中精选）")
    RRF_TOP_K: int = Field(default=100, ge=1, description="混合检索(hybrid 模式) RRF 融合保留条数, 作为重排候选池")
    SUBQUERY_BACKFILL_MAX_TOTAL: int = Field(default=3, ge=0, description="单次请求最多回填的分块数")
    SUBQUERY_BACKFILL_MIN_SCORE: float = Field(default=0.0, ge=0.0, le=1.0, description="兼容旧配置；子问题候选不再因单块分数被硬过滤")
    SUBQUERY_BACKFILL_REQUIRE_ANCHOR: bool = Field(default=False, description="兼容旧配置；不再要求单个分块命中锚点")
    SUBQUERY_CANDIDATE_TOP_K: int = Field(default=3, ge=1, description="每个子查询保留给回填安全检查的候选数")
    SUBQUERY_DECOMPOSE_ENABLED: bool = Field(
            default=True,
            description=(
                "子查询分解总开关: 复合问题（跨主题/一问多面）由 LLM 拆为 2-4 个子查询"
                "分别召回后合并候选池; 单一面问题自动跳过（高频路径零开销）, 分解结果按查询哈希缓存"
            ),
        )
    SUBQUERY_FALLBACK_CACHE_TTL: int = Field(default=300, ge=0, description="规则兜底结果缓存秒数；失败结果不缓存")
    SUBQUERY_MAX_COUNT: int = Field(
            default=4,
            ge=1,
            le=8,
            description="子查询分解的最大子查询数（超出截断）",
        )
    SUBQUERY_MAX_LENGTH: int = Field(default=40, ge=16, description="单个子查询最大字符数")
    SUBQUERY_MAX_TOKENS: int = Field(default=800, ge=64, description="子查询分解单次输出 token 上限")
    SUBQUERY_MIN_FINAL_CHUNKS: int = Field(default=1, ge=0, description="每个有效子问题期望进入最终上下文的最少证据数")
    SUBQUERY_QUOTA_BACKFILL_ENABLED: bool = Field(default=True, description="复合问题未覆盖面是否允许有限证据回填")
    SUBQUERY_RULE_FALLBACK_ENABLED: bool = Field(default=True, description="子查询模型失败时是否启用规则兜底")
    SUBQUERY_TRUNCATION_RETRY_ENABLED: bool = Field(default=True, description="子查询 JSON 截断/解析失败时最多重试一次")

QUERY_CONFIG = QuerySettings()
class ConfigProxy:
    def __getattr__(self, name):
        if hasattr(QUERY_CONFIG, name):
            return getattr(QUERY_CONFIG, name)
        return getattr(BASE_CONFIG, name)
PROJECT_CONFIG = ConfigProxy()
