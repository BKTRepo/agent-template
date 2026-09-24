# -*- coding: utf-8 -*-
"""
@Author  : yangkai
@Email   : 807440781@qq.com
@Project : KeenRobot
@Module  : project_config.py
@DateTime: 2025/1/15 16:08
"""
import os.path
import platform
from functools import lru_cache
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self

from common import FileUtils, ShellUtils

_BACKEND_PROJECT_ROOT: str = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_BACKEND_PROJECT_CONF: str = os.path.join(_BACKEND_PROJECT_ROOT, ".env")


class ProjectConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_BACKEND_PROJECT_CONF,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 项目描述
    APP_VERSION: str = "1.0.0"
    APP_TITLE: str = "企业级RAG问答系统"
    APP_DESCRIPTION: str = """企业级RAG问答系统"""
    APP_DOCS_URL: str = "/docs"
    APP_REDOC_URL: str = "/redoc"
    # 前端 ApiPage 与各层反向代理（vite dev / server.js / nginx）均按默认
    # OpenAPI 地址约定转发, 保持 /openapi.json
    APP_OPENAPI_URL: str = "/openapi.json"
    # 离线 Swagger UI / ReDoc 静态资源: 后端将 static_vendor/swagger/ 挂载在
    # /swagger-assets/ 下（见 app_initialization.register_routers）。不能用
    # /static/... —— 前端反向代理只转发 /swagger-assets 前缀, /static 会被
    # SPA 兜底返回 index.html, 导致 /docs 报 "Unexpected token '<'"
    APP_OPENAPI_JS_URL: str = "/swagger-assets/swagger-ui-bundle.js"
    APP_OPENAPI_CSS_URL: str = "/swagger-assets/swagger-ui.css"
    APP_OPENAPI_FAVICON_URL: str = "/swagger-assets/favicon.png"
    APP_OPENAPI_JS_URL_REDOC: str = "/swagger-assets/redoc.standalone.js"
    APP_OPENAPI_FAVICON_URL_REDOC: str = "/swagger-assets/favicon.png"
    APP_OPENAPI_VERSION: str = "3.0.2"

    # 调试配置
    SERVER_APP: str = "backend_main:app"
    # SERVER_HOST: str = ShellUtils.acquire_localhost()
    SERVER_HOST: str = "0.0.0.0"
    SERVER_SYSTEM: str = platform.system()
    SERVER_PORT: int = 8519
    SERVER_DEBUG: bool = SERVER_SYSTEM != "Linux"  # Windows | Linux | Darwin
    SERVER_DELAY: int = 5
    SERVER_RELOAD_EXCLUDES: List[str] = [
        "*/workspace/*",
        "*/output/*",
        "*/docling_offline/*",
        "*/.venv/*",
        "*/__pycache__/*",
    ]


    # 安全认证配置（必须在.env文件或环境变量中配置）
    AUTH_SECRET_KEY: str = Field(default="", min_length=64, description="JWT密钥，建议: openssl rand -hex 32")
    AUTH_JWT_ALGORITHM: str = "HS256"
    AUTH_JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 day

    # 日志相关参数配置
    LOGGER_FILE_NAME_PREFIX: str = "执行日志"
    # 大小轮转："200 MB"
    # 日期轮转："1 day"、"1 week"、"1 month"
    # 时间轮转："HH:MM:SS"、"00:00"、"00:00:00"
    LOGGER_ROTATION: str = "200 MB"
    # 大小轮转后保留的备份文件个数（单文件多进程模式）
    LOGGER_ROTATION_BACKUP_COUNT: int = 30

    # 项目路径相关配置
    APPLICATIONS_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "applications"))
    CELERY_SCHEDULER_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "celery_scheduler"))
    COMMON_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "common"))
    CONFIGURE_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "configure"))
    CORE_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "core"))
    ENUMS_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "enums"))
    OUTPUT_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "output"))
    OUTPUT_LOGS_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "logs"))
    OUTPUT_UPLOAD_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "upload"))
    OUTPUT_DOWNLOAD_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "download"))
    OUTPUT_MEDIA_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "media"))
    OUTPUT_DATAGRAM_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "datagram"))
    OUTPUT_JMX_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "jmx"))
    OUTPUT_XLSX_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "xlsx"))
    OUTPUT_DOCS_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "docs"))
    SERVICES_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "services"))
    STATIC_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "static"))
    STATIC_IMG_DIR: str = os.path.abspath(os.path.join(STATIC_DIR, "image"))
    MIGRATION_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "migrations"))
    DOCLING_OFFLINE_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "docling_offline"))
    WORKSPACE_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "workspace"))



    # RAG 文档转换输出根目录（每个文档落在 RAG_OUTPUT_DIR/<job_id>/ 下）
    RAG_OUTPUT_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "output", "rag_upload"))
    # RAG 上传源文件留存根目录（每个文档落在 RAG_INPUT_DIR/<job_id>/ 下,
    # 供解析失败时从源文件重试, 允许重复文件名后以 job_id 隔离）
    RAG_INPUT_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "input"))
    # 服务端允许的上传文件大小上限（MB）: 前端 200MB 校验可被绕过, 服务端须独立设防
    RAG_MAX_UPLOAD_MB: int = Field(default=200, ge=1, description="服务端上传文件大小上限(MB)")
    # 项目根目录（public，供 static_vendor 等跨目录资源定位）
    PROJECT_ROOT: str = _BACKEND_PROJECT_ROOT
    DOCLING_PDF_BACKEND: str = Field(
        default="pypdfium2",
        description=(
            "PDF 解析后端: pypdfium2（内存高效, 大文件推荐）/ "
            "docling_parse（表格质量更高, 内存占用大）"
        ),
    )
    DOCLING_USE_GPU: bool = Field(
        default=True,
        description=(
            "docling 的 torch 模型（版面/表格/图片分类）是否使用 CUDA; "
            "false = 纯 CPU。OCR 走 onnxruntime 恒为 CPU, 不受此开关控制"
        ),
    )
    DOCLING_FORMULA_ENRICHMENT: bool = Field(default=False, description="是否启用公式增强")
    DOCLING_TABLE_STRUCTURE: bool = Field(default=True, description="是否启用表格结构识别")
    # 图片分类: 使用 docling_offline/docling/models 内的 DocumentFigureClassifier 模型
    DOCLING_PICTURE_CLASSIFICATION: bool = Field(default=True, description="是否启用图片分类（离线模型已内置）")
    # 图片描述: 需要 SmolVLM 模型（约 600MB）, 离线缓存默认未包含;
    # 如需开启, 先执行: docling-tools models download-hf-repo HuggingFaceTB/SmolVLM-256M-Instruct
    # 并把下载的 HuggingFaceTB--SmolVLM-256M-Instruct 目录移入 docling_offline/docling/models/
    DOCLING_PICTURE_DESCRIPTION: bool = Field(default=False, description="是否启用图片描述（需本地 SmolVLM 模型）")
    CHUNK_OVERLAP_SIZE: int = Field(default=100, description="分块重叠大小，应 ≤ CHUNK_SIZE/2")
    TABLE_ROW_CHUNKS: bool = Field(
        default=True,
        description=(
            "表格行级分块开关: 开启后为每张非目录表格生成 1 个表级摘要块 + "
            "逐行块（行数据 + 表名/行号元数据 + 自然语言描述, 纯规则生成不依赖 VLM）, "
            "与文本块并存嵌入入库"
        ),
    )
    TABLE_ANCHOR_PATTERN: str = Field(
        default=r"\b[A-Z]{2,6}\s*\d+",
        description=(
            "表格命名锚点标题的正则: 表格块命名时向前回溯标题流, 最近命中该模式的标题"
            "作为'字段定义锚点'（如 'DE 3 (Processing Code)'）前置到表名, 使扁平标题文档"
            "（全 ## 层级）里的表格块携带 DE 级祖先词汇, 可被 '3域/DE 3' 类查询命中。"
            "置空字符串禁用锚点回溯。注意: 文档尾部与锚点章节无关的表格（如附录）在窗口内"
            "可能被误挂祖先锚点, 介意时可调小扫描窗口或禁用"
        ),
    )
    TABLE_ANCHOR_SCAN_WINDOW: int = Field(
        default=20,
        ge=1,
        description="表格命名锚点回溯的最近标题扫描窗口（个）; 窗口内无命中则不前置锚点（仅大纲模式禁用时的回落路径使用）",
    )
    TABLE_OUTLINE_LEVELS: List[str] = Field(
        default=[r"^DE\s*\d+\b", r"^Subelement\s*\d+\b", r"^Subfield\s*\d+\b"],
        description=(
            "表格命名语义大纲的层级正则（有序列表, 位置即深度: 默认 DE=章节级, "
            "Subelement=节级, Subfield=小节级）。标题命中深度 k 时弹栈至深度<k 再压栈, 按角色维护"
            "逻辑大纲; 表格命名取栈内祖先 + 节内 context 标题 + 表格前导标题"
            "拼成完整定位路径"
            "（如 'DE 3 (Processing Code) > Subfield 2 (...) > Cardholder \"From Account\" "
            "type code'）, 解决扁平标题（全 ##）文档里两槽位命名被中间节顶掉、窗口"
            "锚点回溯超窗落空的问题。未命中任何层级的非样板标题作节 context "
            "与表题候选。表格处大纲栈为空时回落两槽位+锚点回溯。空列表禁用大纲模式"
        ),
    )
    TABLE_HEADING_STOPLIST: List[str] = Field(
        default=["Values", "Attributes", "Usage", "Application notes"],
        description=(
            "表格命名大纲的样板标题停用表（忽略大小写精确匹配）: 这些标题在每个"
            "字段/小节下机械重复、不携带区分信息, 不进入表名祖先链; 但作为表格"
            "紧邻前导标题时仍可用作表题。仅大纲模式生效"
        ),
    )
    TABLE_OUTLINE_RESET_PATTERN: str = Field(
        default=r"^(Appendix|Index|Glossary|Table of Contents)\b",
        description=(
            "表格命名大纲的重置标题正则: 命中标题时清空大纲栈, 用于附录/索引等与"
            "正文字段定义无关的尾部章节, 防止其后的表格误挂正文最后一个锚点祖先。"
            "空字符串禁用重置。仅大纲模式生效"
        ),
    )
    CHUNK_TOP_K: int = Field(default=100, ge=1, description="向量检索(naive 模式)稠密检索返回的分块条数")
    RRF_TOP_K: int = Field(default=100, ge=1, description="混合检索(hybrid 模式) RRF 融合保留条数, 作为重排候选池")
    HYBRID_DENSE_TOP_K: int = Field(default=60, description="混合检索每路稠密检索的候选数（未显式传 dense_top_k 时生效）")
    HYBRID_BM25_TOP_K: int = Field(default=60, description="混合检索每路 BM25 检索的候选数（未显式传 bm25_top_k 时生效）")
    RAG_CONTEXT_TOP_K: int = Field(
        default=20,
        ge=1,
        description="重排后送入生成模型的最大分块数；候选池仍保留较大 top-k 供重排",
    )
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
    BM25_FINGERPRINT_TTL: float = Field(
        default=30.0,
        description=(
            "BM25 索引新鲜度指纹的 Web 侧缓存 TTL（秒）: TTL 内不向向量库"
            "查询指纹。新入库数据最多延迟 TTL 秒进入 BM25 关键词检索; "
            "设为 0 则每次查询都核对指纹"
        ),
    )
    DOC_RECALL_ENABLED: bool = Field(
        default=True,
        description=(
            "文档级召回总开关（文档摘要索引 + 定向注入）: 查询与文档摘要余弦"
            "匹配命中的文档, 定向召回其 top 分块注入重排候选池。摘要层只保证"
            "涉及文档被认真考虑, 是否进最终窗口仍由重排阈值唯一决定（双闸门）"
        ),
    )
    DOC_RECALL_MIN_SCORE: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="查询向量与文档摘要向量的余弦相似度阈值, 达标文档判定为问题涉及文档（需 A/B 校准）",
    )
    DOC_RECALL_CHUNKS_PER_DOC: int = Field(
        default=8,
        ge=1,
        description="每份命中文档定向注入候选池的分块数上限",
    )
    DOC_RECALL_MAX_DOCS: int = Field(
        default=3,
        ge=1,
        description="单次查询最多定向注入的文档数（按摘要相似度取 top, 控制增量 RPC 与候选池规模）",
    )
    DOC_RECALL_INDEX_TTL: float = Field(
        default=30.0,
        description=(
            "文档摘要索引新鲜度指纹的 Web 侧缓存 TTL（秒）: TTL 内不核对文档表指纹。"
            "新入库文档最多延迟 TTL 秒进入文档级召回; 设为 0 则每次查询都核对"
        ),
    )
    QUERY_MEMORY_ENABLED: bool = Field(
        default=True,
        description="是否启用采纳经验查询指导；关闭时直接走全库检索",
    )
    QUERY_MEMORY_SHADOW_MODE: bool = Field(
        default=False,
        description="影子模式：记录采纳经验命中但不使用文档范围限制实际检索",
    )
    QUERY_MEMORY_SCOPED_SEARCH_ENABLED: bool = Field(
        default=False,
        description="是否用采纳经验范围加权召回，同时保留全库候选参与统一重排",
    )
    QUERY_MEMORY_GUIDED_WEIGHT: float = Field(
        default=1.2,
        ge=1.0,
        description="历史范围候选在融合阶段的 RRF 权重",
    )
    QUERY_MEMORY_GLOBAL_MIN_RATIO: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="候选池为全库其他文档预留的最低比例；最终由统一重排决定是否采用",
    )
    QUERY_MEMORY_TOP_K: int = Field(
        default=5,
        ge=1,
        description="查询指导最多召回的采纳经验条数",
    )
    QUERY_MEMORY_MIN_SCORE: float = Field(
        default=0.72,
        ge=-1.0,
        le=1.0,
        description="查询经验余弦相似度最低阈值；低于此值不限定文档范围",
    )
    LEARNED_MAPPING_MIN_EVIDENCE: int = Field(
        default=2,
        ge=2,
        description="程序映射进入候选状态所需的独立采纳证据数",
    )
    MAPPING_EVIDENCE_MIN_SCORE: float = Field(
        default=0.72,
        ge=-1.0,
        le=1.0,
        description="映射证据问题的最低语义相似度；每条证据须与组内成员及组中心达标",
    )
    MAPPING_EVIDENCE_MIN_CONFIDENCE: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="模型提取映射的最低自评置信度；低于此值的证据保留但不计入自动激活",
    )
    MAPPING_EVIDENCE_CENTROID_MIN_SCORE: float = Field(
        default=0.90,
        ge=-1.0,
        le=1.0,
        description="证据问题与所在组中心向量的最低相似度",
    )
    MAPPING_EXTRACTION_ENABLED: bool = Field(
        default=True,
        description="是否在采纳后异步提取程序映射证据",
    )
    DOC_SUMMARY_INPUT_MAX_CHARS: int = Field(
        default=20000,
        ge=1000,
        description="生成文档摘要时送入 LLM 的正文最大字符数（头部优先, 尾部补足）",
    )
    SUBQUERY_DECOMPOSE_ENABLED: bool = Field(
        default=True,
        description=(
            "子查询分解总开关: 复合问题（跨主题/一问多面）由 LLM 拆为 2-4 个子查询"
            "分别召回后合并候选池; 单一面问题自动跳过（高频路径零开销）, 分解结果按查询哈希缓存"
        ),
    )
    SUBQUERY_MAX_COUNT: int = Field(
        default=4,
        ge=1,
        le=8,
        description="子查询分解的最大子查询数（超出截断）",
    )
    MAX_TOTAL_TOKENS: int = Field(default=30000, description="上下文 token 总预算上限")
    PDF_SPLIT_MAX_PAGES: int = Field(
        default=25,
        description=(
            "大文档切分阈值（超过该页数的 PDF 自动切分为子文档后解析）。"
            "该值同时决定取消粒度——docling 单子文档转换不可打断, 取消在子文档之间的"
            "检查点生效, 阈值越小取消响应等待越短"
        ),
    )
    MAX_PARALLEL_PARSE_DOCLING: int = Field(default=1, description="子文档解析并行数（每槽位各自拥有独立解析器）")
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
    CHAT_SUMMARY_MAX_TOKENS: int = Field(
        default=500,
        ge=0,
        description=(
            "滚动摘要自身的目标 token 体积（保持精炼）。"
            "摘要作为背景上下文注入 system, 其 token 计入总预算"
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
    TERMINOLOGY_BATCH_CONCURRENCY: int = Field(default=5, description="术语抽取 LLM 批次并发数")
    TERMINOLOGY_MAX_TOKENS: int = Field(
        default=16384,
        description=(
            "术语抽取单批 LLM 输出 token 上限。偏低会导致输出截断"
            "（finish_reason=length）——检测到截断后会自动把该批对半重切重试, "
            "实体编号密集的大文档建议按所用模型的能力上限调高该值"
        ),
    )
    TERMINOLOGY_ENTITY_MAX_ITEMS: int = Field(
        default=20,
        ge=1,
        description=(
            "术语表保留的编号实体组最大条目数: 合并后条目数超过该值的组判定为"
            "纯值域枚举（代码值表/响应码表等）, 整组丢弃——取值不是术语, "
            "不参与查询改写; 少量编号的锚点组（如 DE 1~6）保留"
        ),
    )

    # ==================== 向量数据库配置 ====================
    VECTOR_BACKEND: Literal["milvus"] = Field(
        default="milvus",
        description="固定使用 Milvus Server C/S 后端",
    )
    MILVUS_URI: str = Field(
        default="http://127.0.0.1:19530",
        description="Milvus Server URI；仅支持 C/S 架构"
    )
    MILVUS_USER: Optional[str] = Field(default=None, description="Milvus 用户名（可选）")
    MILVUS_PASSWORD: Optional[str] = Field(default=None, description="Milvus 密码（可选）")
    MILVUS_TOKEN: Optional[str] = Field(default=None, description="Milvus Token（可选）")
    MILVUS_POOL_SIZE: int = Field(
        default=8,
        ge=1,
        description="单进程 Milvus 同步客户端连接池上限",
    )
    MILVUS_POOL_ACQUIRE_TIMEOUT: float = Field(
        default=30.0,
        gt=0,
        description="等待 Milvus 连接池空闲连接的最长秒数",
    )
    VECTOR_UPSERT_BATCH_SIZE: int = Field(
        default=500,
        description=(
            "向量库 upsert 单批写入条数: 大文档数千分块一次性写入时 payload "
            "可达数十 MB, 可能触及 gRPC 消息上限导致整篇在最后一步失败; "
            "分批写入（块 ID 幂等, 失败重试安全）规避该风险"
        ),
    )
    LLM_MODEL: str = Field(default="deepseek-chat", description="默认 LLM 模型")
    LLM_MAX_TOKENS: int = Field(default=4096, description="LLM 单次最大生成 token 数")
    LLM_TEMPERATURE: float = Field(default=0.7, description="LLM 默认采样温度")

    # ==================== Embedding 配置 ====================
    EMBEDDING_BINDING_HOST: str = Field(default="https://api.siliconflow.cn/v1", description="Embedding API Base URL")
    EMBEDDING_BINDING_API_KEY: str = Field(default="", description="Embedding API Key")
    EMBEDDING_MODEL: str = Field(default="BAAI/bge-m3", description="默认 Embedding 模型")
    EMBEDDING_DIM: int = Field(default=1024, description="向量维度（Milvus 建集合使用）")
    EMBEDDING_BATCH_NUM: int = Field(
        default=20,
        ge=1,
        le=20,
        description=(
            "Embedding 单次请求条数。当前百炼 OpenAI 兼容嵌入接口要求 "
            "input.contents 不超过 20 条；在配置层强制上限，避免大文档到最后阶段才失败"
        ),
    )
    EMBEDDING_MAX_CONCURRENT: int = Field(
        default=10,
        description=(
            "Embedding API 最大并发请求数。两个约束: ① Windows 的 asyncio "
            "SelectorEventLoop 底层 select() 有 512 socket 硬上限; "
            "② 供应商 TPM（tokens/分钟）配额——并发越高单位时间灌入的 "
            "token 越多, 越容易触发 429 限流。大文档频繁 429 时应继续调小"
        ),
    )
    EMBEDDING_SEND_DIM: bool = Field(default=False, description="请求时是否显式传递维度参数")
    EMBEDDING_USE_BASE64: bool = Field(default=True, description="是否使用 base64 编码传输向量")
    EMBEDDING_MAX_CHARS_PER_TEXT: int = Field(
        default=5000,
        description=(
            "嵌入输入单条文本的字符上限, 超限部分截断后再向量化。"
            "需覆盖最大分块长度（分块口径 CHUNK_SIZE × 每 token 1.3 字符 ≈ 1560 + 缓冲）, "
            "否则分块尾部内容不参与向量化, 尾部关键词的稠密检索命中率下降"
        ),
    )

    # ==================== Rerank 配置 ====================
    RERANK_BINDING_HOST: str = Field(default="https://api.siliconflow.cn/v1/rerank", description="Rerank API 地址")
    RERANK_MODEL: str = Field(default="BAAI/bge-reranker-v2-m3", description="Rerank 模型")
    RERANK_BINDING_API_KEY: str = Field(default="", description="Rerank API Key")
    RERANK_ENABLE_CHUNKING: bool = Field(default=True, description="长文档是否切块后再重排")
    RERANK_MAX_TOKENS_PER_DOC: int = Field(default=480, description="重排切块的单块 token 上限")
    RERANK_TOP_K: int = Field(default=50, ge=1, description="重排后最多返回的分块数（最终检索窗口, 从候选池中精选）")
    RERANK_MIN_SCORE: float = Field(default=0.0, description="重排最低分数阈值")

    # ==================== VLM 多模态配置 ====================
    ENABLE_VLM: bool = Field(default=False, description="是否默认启用 VLM 多模态分析")
    VLM_API_BASE: str = Field(default="http://127.0.0.1:11434/v1", description="VLM API Base URL (OpenAI 兼容)")
    VLM_MODEL: str = Field(default="gpt-4o", description="VLM 模型")
    VLM_API_KEY: str = Field(default="not-needed", description="VLM API Key")
    # RAG / LLM / Embedding
    LLM_API_KEY: str = Field(default="", description="LLM API Key")
    LLM_BASE_URL: str = Field(default="https://api.deepseek.com/v1", description="LLM API Base URL")
    LLM_MODEL_NAME: str = Field(default="deepseek-chat", description="LLM Model Name")
    EMBEDDING_API_KEY: str = Field(default="", description="Embedding API Key")
    EMBEDDING_BASE_URL: str = Field(default="", description="Embedding API Base URL")
    EMBEDDING_MODEL_NAME: str = Field(default="", description="Embedding Model Name")

    # RAG 分块 / 检索全局默认值（.env 可选；不写则用下列 default）
    # - CHUNK_SIZE / CHUNK_OVERLAP：KnowledgeBase.chunk_* 为空时回退；仅影响新上传/重处理文档
    # - RETRIEVAL_TOP_K：旧知识库 Milvus 检索 top_k 为空时兜底；聊天链路以 ModelConfig.top_k 为准
    CHUNK_SIZE: int = Field(
        default=500,
        description="分块大小(字符数)；知识库未配置时回退，建议 200-2000",
    )
    CHUNK_OVERLAP: int = Field(
        default=100,
        description="分块重叠(字符数)；知识库未配置时回退，应 ≤ CHUNK_SIZE/2",
    )
    RETRIEVAL_TOP_K: int = Field(
        default=5,
        description="向量检索条数兜底；聊天以 ModelConfig.top_k(1-20) 为准",
    )

    # 测试用例生成配置
    TEST_CASE_MODEL_POOL: str = Field(
        default="sonnet;haiku;opus",
        description="Claude 模型池（短别名或具体模型名，用分号分隔，按顺序轮询）",
    )
    TEST_CASE_MODEL_TIMEOUT: int = Field(default=1200, description="单个模型调用超时秒数")
    TEST_CASE_SKILLS: str = Field(
        default="test-case-generator",
        description="测试用例生成启用的 Claude skills，多个值使用分号分隔",
    )
    TEST_CASE_OUTPUT_DIR: str = Field(
        default=os.path.abspath(os.path.join(WORKSPACE_DIR, "test_case")),
        description="测试用例生成任务和产物目录",
    )

    # 环境工单预审
    TICKET_REVIEW_ENABLED: bool = Field(
        default=True,
        description="工单预审模块总开关: False 时启动跳过 ticket_review 的数据库池与 Worker",
    )
    TICKET_MODEL_POOL: str = "claude-sonnet-4-6;claude-opus-4-6;claude-haiku-4-5-20251001"
    TICKET_MODEL_TIMEOUT: int = 1200
    TICKET_MODEL_RETRY_COUNT: int = 2
    TICKET_MODEL_RETRY_DELAY: int = 3
    TICKET_SDK_MODEL_POOL: str = ""
    TICKET_ANTHROPIC_MODEL: str = ""
    TICKET_COCO_BATCH_SIZE: int = 10
    TICKET_DB1_HOST: str = ""
    TICKET_DB1_PORT: int = 3306
    TICKET_DB1_USER: str = ""
    TICKET_DB1_PASSWORD: str = ""
    TICKET_DB1_NAME: str = ""
    TICKET_DB1_POOL_MIN_SIZE: int = 1
    TICKET_DB1_POOL_MAX_SIZE: int = 5
    TICKET_DB1_CONNECT_TIMEOUT: int = 10
    TICKET_DB2_HOST: str = ""
    TICKET_DB2_PORT: int = 3306
    TICKET_DB2_USER: str = ""
    TICKET_DB2_PASSWORD: str = ""
    TICKET_DB2_NAME: str = ""
    TICKET_DB2_POOL_MIN_SIZE: int = 1
    TICKET_DB2_POOL_MAX_SIZE: int = 5
    TICKET_DB2_CONNECT_TIMEOUT: int = 10
    TICKET_PUSH_TASK_WORKER_ENABLED: bool = True
    TICKET_PUSH_TASK_POLL_INTERVAL: int = 2
    TICKET_PUSH_TASK_BATCH_SIZE: int = 5
    TICKET_PUSH_TASK_RETENTION_DAYS: int = 7
    TICKET_PUSH_TASK_CLEANUP_INTERVAL: int = 3600
    TICKET_PUSH_TASK_STALE_PROCESSING_SECONDS: int = 1800
    TICKET_PUSH_TASK_FAILED_RETRY_DELAY_SECONDS: int = 86400
    TICKET_PUSH_TASK_SSE_HEARTBEAT_SECONDS: int = 15
    TICKET_PUSH_TASK_HEARTBEAT_INTERVAL_SECONDS: int = 60

    # Code Server IDE
    CODE_SERVER_IDE_ENABLED: bool = Field(
        default=True,
        description="Code Server IDE 模块总开关: False 时启动跳过 IDE 数据库与后台任务",
    )
    IDE_DATABASE_HOST: str = ""
    IDE_DATABASE_PORT: int = 3306
    IDE_DATABASE_USER: str = ""
    IDE_DATABASE_PASSWORD: str = ""
    IDE_DATABASE_NAME: str = ""
    IDE_DATABASE_URL: str = ""
    IDE_DATABASE_ECHO: bool = False
    IDE_IMAGE: str = "coco-code-server:amd64-20260730"
    IDE_DOCKER_NETWORK: str = "coco-ide-net"
    IDE_CONTAINER_PREFIX: str = "ide-code-server"
    IDE_SESSIONS_ROOT: str = "~/claude_engineering/ide-sessions"
    IDE_CODE_SERVER_AUTH: str = "none"
    IDE_AUTH_COOKIE_NAME: str = "ide_access_token"
    IDE_UID: int = 1001
    IDE_BASE_HOST_PORT: int = 18081
    IDE_HOST_PORT_RANGE: int = 1000
    IDE_MEMORY_LIMIT: str = "2g"
    IDE_MEMORY_SWAP_LIMIT: str = "2g"
    IDE_CPU_LIMIT: str = "2"
    IDE_PIDS_LIMIT: str = "512"
    COCO_NPM_REGISTRY: str = "https://registry.npmmirror.com"
    COCO_PIP_INDEX_URL: str = "https://mirrors.aliyun.com/pypi/simple/"
    COCO_PIP_TRUSTED_HOST: str = "mirrors.aliyun.com"
    IDE_MAX_RUNNING_CONTAINERS: int = 0
    IDE_IDLE_STOP_MINUTES: int = 30
    IDE_IDLE_PENDING_MINUTES: int = 5
    IDE_STOPPING_TIMEOUT_MINUTES: int = 5
    IDE_DOCKER_STOP_TIMEOUT_SECONDS: int = 30
    IDE_STOPPED_CONTAINER_RM_MINUTES: int = 1440
    IDE_BUSY_FILE_WINDOW_MINUTES: int = 2
    IDE_BUSY_CPU_THRESHOLD: float = 2
    IDE_BUSY_MAX_HOURS: int = 6
    IDE_DATA_RETENTION_DAYS: int = 7
    IDE_ALLOW_VIEW_OTHER_USERS_PROJECTS: bool = True
    IDE_ALLOW_CROSS_USER_EDIT_IN_SYSTEM: bool = False

    # # 允许访问的源（域名）列表
    CORS_ORIGINS: List[str] = [
        "http://localhost",
        "http://localhost:5000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://localhost:8515",
        "*",
    ]
    # 是否允许携带凭证（如 cookies）
    CORS_ALLOW_CREDENTIALS: bool = True
    # 允许的 HTTP 方法列表
    CORS_ALLOW_METHODS: List[str] = ["*"]
    # 允许的请求头列表
    CORS_ALLOW_HEADERS: List[str] = ["*"]
    # 允许客户端访问的响应头列表
    CORS_EXPOSE_METHODS: List[str] = ["*"]
    # 预检请求的缓存时间（秒）
    CORS_MAX_AGE: int = 600

    # 文件上传设置
    UPLOAD_FILE_BASE_SIZE: int = 1024 * 1024  # 1MB
    UPLOAD_FILE_PEAK_SIZE: Dict[str, int] = {
        "tiny": UPLOAD_FILE_BASE_SIZE * 16,
        "micro": UPLOAD_FILE_BASE_SIZE * 32,
        "small": UPLOAD_FILE_BASE_SIZE * 64,
        "medium": UPLOAD_FILE_BASE_SIZE * 128,
        "large": UPLOAD_FILE_BASE_SIZE * 256,
        "huge": UPLOAD_FILE_BASE_SIZE * 512,
    }
    UPLOAD_FILE_SUFFIX: List[str] = [
        'image/jepg',
        'image/png',
        'text/csv',
        'text/plain',
        'text/markdown',
        'application/pdf',
        'application/zip',
        'application/msword',  # doc
        'application/octet-stream',  # dat
        'application/vnd.ms-excel',  # xls
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # xlsx
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'  # docx
    ]

    # 应用注册
    APPLICATIONS_MODULE: str = "applications"
    APPLICATIONS_INSTALLED: List[str] = FileUtils.get_all_dirs(
        abspath=APPLICATIONS_DIR,
        return_full_path=False,
        exclude_startswith="__",
        exclude_endswith="__",
    )

    @property
    def APPLICATIONS_MODELS(self) -> List[str]:
        models = [
            models
            for app in self.APPLICATIONS_INSTALLED
            for models in FileUtils.get_all_files(
                abspath=os.path.join(self.APPLICATIONS_DIR, app, "models"),
                return_full_path=False,
                return_precut_path=f"{self.APPLICATIONS_MODULE}.{app}.models.",
                endswith="model",
                exclude_startswith="__",
                exclude_endswith="__.py"
            )
        ]
        models.append("aerich.models")
        return models

    # 常用的用户代理字符串列表
    USER_AGENTS: List[str] = [
        # Chrome
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",

        # Firefox
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Mozilla/5.0 (X11; Linux i686; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:119.0) Gecko/20100101 Firefox/119.0",

        # Safari
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",

        # Edge
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",

        # Mobile
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    ]

    # 数据库配置（仅支持 MySQL）
    # DATABASE_AUTO_MIGRATION字段默认关闭，不做数据库模型迁移，如果需要请先检查或询问当前数据库模型是否存在更新，避免迁移记录错乱
    DATABASE_AUTO_MIGRATION: bool = False
    DATABASE_CONNECTIONS: Dict[str, Any] = {}
    DATABASE_URL: str = Field(default="", description="数据库地址")
    DATABASE_HOST: str = Field(default="", description="数据库主机")
    DATABASE_PORT: str = Field(default="", description="数据库端口")
    DATABASE_NAME: str = Field(default="", description="数据库名称")
    DATABASE_USERNAME: str = Field(default="", description="数据库用户名")
    DATABASE_PASSWORD: str = Field(default="", description="数据库密码")

    # Redis 配置
    REDIS_URL: str = ""
    REDIS_HOST: str = Field(default="", description="Redis主机")
    REDIS_PORT: str = Field(default="", description="Redis端口")
    REDIS_USERNAME: str = Field(default="", description="Redis用户名")
    REDIS_PASSWORD: str = Field(default="", description="Redis密码")

    @model_validator(mode="after")
    def validate_env_and_assemble_urls(self) -> Self:
        if not self.AUTH_SECRET_KEY or len(self.AUTH_SECRET_KEY) < 64:
            raise ValueError("AUTH_SECRET_KEY 配置为空或长度少于64位，请检查.env文件或环境变量")

        for field_name in ("DATABASE_USERNAME", "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} 配置为空，请检查.env文件或环境变量")

        if not self.MILVUS_URI.strip().lower().startswith(("http://", "https://")):
            raise ValueError("MILVUS_URI 必须是独立 Milvus Server 的 http(s) 地址")

        Path(self.OUTPUT_UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.OUTPUT_DATAGRAM_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.OUTPUT_LOGS_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.RAG_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.RAG_INPUT_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.TEST_CASE_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

        return self.assemble_connection_urls()

    def assemble_connection_urls(self) -> Self:
        db_user = quote_plus(self.DATABASE_USERNAME)
        db_password = quote_plus(self.DATABASE_PASSWORD)
        self.DATABASE_URL = (
            f"mysql://{db_user}:{db_password}@{self.DATABASE_HOST}:"
            f"{self.DATABASE_PORT}/{self.DATABASE_NAME}"
            f"?charset=utf8mb4&time_zone=+08:00"
        )
        self.DATABASE_CONNECTIONS = {
            "default": {
                "engine": "tortoise.backends.mysql",
                "credentials": {
                    "host": self.DATABASE_HOST,
                    "port": self.DATABASE_PORT,
                    "user": self.DATABASE_USERNAME,
                    "password": self.DATABASE_PASSWORD,
                    "database": self.DATABASE_NAME,
                    "minsize": 10,
                    "maxsize": 40,
                    "pool_recycle": 3600,
                    "charset": "utf8mb4",
                    "echo": False,
                    "autocommit": True,
                },
            }
        }

        ide_db_user = quote_plus(self.IDE_DATABASE_USER)
        ide_db_password = quote_plus(self.IDE_DATABASE_PASSWORD)
        self.IDE_DATABASE_URL = (
            f"mysql+aiomysql://{ide_db_user}:{ide_db_password}"
            f"@{self.IDE_DATABASE_HOST}:{self.IDE_DATABASE_PORT}/"
            f"{self.IDE_DATABASE_NAME}?charset=utf8mb4"
        )
        self.IDE_CODE_SERVER_AUTH = self.IDE_CODE_SERVER_AUTH.strip().lower() or "none"
        if self.IDE_CODE_SERVER_AUTH != "none":
            raise ValueError("Only IDE_CODE_SERVER_AUTH=none is supported")

        if self.REDIS_PASSWORD:
            self.REDIS_URL = self.build_redis_url(db=0)
        return self

    @property
    def upload_path(self) -> Path:
        return Path(self.OUTPUT_UPLOAD_DIR)

    @property
    def datagram_path(self) -> Path:
        return Path(self.OUTPUT_DATAGRAM_DIR)

    @staticmethod
    def format_redis_url(*, username: str, password: str, host: str, port: str, db: int) -> str:
        auth = ""
        if username:
            auth += quote_plus(username)
        auth += ":"
        if password:
            auth += quote_plus(password)
        auth += "@"
        return f"redis://{auth}{host or '127.0.0.1'}:{port or '6379'}/{db}"

    def build_redis_url(self, db: int = 0) -> str:
        return self.format_redis_url(
            username=self.REDIS_USERNAME,
            password=self.REDIS_PASSWORD,
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            db=db,
        )

    # Aerich：是否在应用启动时执行 init_db / migrate / upgrade 指令
    # - 生产(Linux 且 SERVER_DEBUG=False)：始终执行迁移（不提供关闭选项）
    # - 开发(SERVER_DEBUG=True)：默认不迁移；需要时由开发者手动把 DATABASE_AUTO_MIGRATION 改为 True
    @property
    def aerich_should_run_on_startup(self) -> bool:
        if (not self.SERVER_DEBUG) and (self.SERVER_SYSTEM == "Linux"):
            return True
        if self.SERVER_DEBUG and self.DATABASE_AUTO_MIGRATION:
            return True
        return False


@lru_cache(maxsize=1)
def get_project_config() -> ProjectConfig:
    return ProjectConfig()


PROJECT_CONFIG = get_project_config()

# Aerich CLI 入口；与应用启动时 register_database 使用同一套模型和连接配置。
TORTOISE_ORM = {
    "connections": PROJECT_CONFIG.DATABASE_CONNECTIONS,
    "apps": {
        "models": {
            "models": PROJECT_CONFIG.APPLICATIONS_MODELS,
            "default_connection": "default",
        }
    },
    "use_tz": False,
    "timezone": "Asia/Shanghai",
}
