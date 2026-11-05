# -*- coding: utf-8 -*-
"""通用后端配置。"""
import os.path
import platform
import ssl
from functools import lru_cache
from pathlib import Path
from typing import List, Dict, Any, Literal, Optional
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

    # dev-knowledge: document ingestion configuration (no source credentials).
    RAG_INPUT_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "input"))
    RAG_MAX_UPLOAD_MB: int = Field(default=200, ge=1, description="服务端上传文件大小上限(MB)")
    MAX_DELETING_RECOMPENSATE: int = Field(
            default=5,
            ge=1,
            description="单个 deleting 文档允许被巡检重新投递的最大次数",
        )
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
    DOC_SUMMARY_INPUT_MAX_CHARS: int = Field(
            default=20000,
            ge=1000,
            description="生成文档摘要时送入 LLM 的正文最大字符数（头部优先, 尾部补足）",
        )
    TERMINOLOGY_BATCH_CONCURRENCY: int = Field(default=5, description="术语抽取 LLM 批次并发数")
    TERMINOLOGY_BATCH_RAW_CHARS: int = Field(
            default=30000,
            ge=8000,
            description="术语抽取单批原始 Markdown 字符上限",
        )
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
    LLM_MAX_TOKENS: int = Field(default=8192, description="LLM 单次最大生成 token 数")
    LLM_TEMPERATURE: float = Field(default=0.7, description="LLM 默认采样温度")
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
            default=1,
            ge=1,
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
    ENABLE_VLM: bool = Field(default=False, description="是否默认启用 VLM 多模态分析")
    VLM_API_BASE: str = Field(default="http://127.0.0.1:11434/v1", description="VLM API Base URL (OpenAI 兼容)")
    VLM_MODEL: str = Field(default="gpt-4o", description="VLM 模型")
    VLM_API_KEY: str = Field(default="not-needed", description="VLM API Key")

    # 项目描述
    APP_VERSION: str = "1.0.0"
    APP_TITLE: str = "FastAPI Template"
    APP_DESCRIPTION: str = "通用 FastAPI 后端模板"
    APP_DOCS_URL: str = "/docs"
    APP_REDOC_URL: str = "/redoc"
    APP_OPENAPI_URL: str = "/openapi_url"
    APP_OPENAPI_JS_URL: str = "/static/swagger-ui/swagger-ui-bundle.js"
    APP_OPENAPI_CSS_URL: str = "/static/swagger-ui/swagger-ui.css"
    APP_OPENAPI_FAVICON_URL: str = "/static/swagger-ui/favicon-32x32.png"
    APP_OPENAPI_JS_URL_REDOC: str = "/static/redoc/bundles/redoc.standalone.js"
    APP_OPENAPI_FAVICON_URL_REDOC: str = "/static/redoc/favicon.png"
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
    CHROMA_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "core", "chroma_db"))
    DOCLING_OFFLINE_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "docling_offline"))
    WORKSPACE_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "workspace"))
    # 独立构建目录，不把草稿自动安装进共享 Agent 工作区。
    SKILL_BUILD_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "skill-builds"))
    # 20261016 定稿：Skill 直接上传单文件/合计均为 50M；与前端统一使用 MiB。
    SKILL_RESOURCE_MAX_BYTES: int = Field(default=50 * 1024 * 1024, gt=0)
    SKILL_RESOURCE_TOTAL_MAX_BYTES: int = Field(default=50 * 1024 * 1024, gt=0)
    APPLICATION_CATALOG_MODE: Literal["mock", "remote"] = "mock"
    APPLICATION_CATALOG_URL: str = "http://10.240.105.84:9999/selfTest/queryAllApplication"
    APPLICATION_CATALOG_CACHE_SECONDS: int = Field(default=60, ge=0)
    KNOWLEDGE_PDF_DOCLING: bool = False
    KNOWLEDGE_RAG_ENV_FILE: str = ""
    # 正式默认走持久 Celery；inline 仅用于隔离测试和单机演示。
    KNOWLEDGE_TASK_MODE: Literal["celery", "inline"] = "celery"
    KNOWLEDGE_CANCEL_POLL_SECONDS: float = Field(default=1.0, gt=0)
    KNOWLEDGE_LOCK_TTL_SECONDS: int = Field(default=60, ge=10)
    KNOWLEDGE_JOB_STALE_SECONDS: int = Field(default=300, ge=30)
    KNOWLEDGE_DELETE_MAX_RETRIES: int = Field(default=12, ge=0)
    DOCLING_TABLE_STRUCTURE: bool = True
    DOCLING_FORMULA_ENRICHMENT: bool = False
    DOCLING_PICTURE_CLASSIFICATION: bool = False
    DOCLING_PICTURE_DESCRIPTION: bool = False
    DOCLING_USE_GPU: bool = False
    DOCLING_PDF_BACKEND: str = "pypdfium2"
    RAG_OUTPUT_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "knowledge-parsed"))



    # RAG / LLM / Embedding
    CHROMA_COLLECTION: str = "knowledge_base"
    LLM_API_KEY: str = Field(default="", description="LLM API Key")
    LLM_BASE_URL: str = Field(default="", description="LLM API Base URL")
    LLM_MODEL_NAME: str = Field(default="", description="LLM Model Name")
    EMBEDDING_API_KEY: str = Field(default="", description="Embedding API Key")
    EMBEDDING_BASE_URL: str = Field(default="", description="Embedding API Base URL")
    EMBEDDING_MODEL_NAME: str = Field(default="", description="Embedding Model Name")

    # RAG 分块 / 检索全局默认值（.env 可选；不写则用下列 default）
    # - CHUNK_SIZE / CHUNK_OVERLAP：KnowledgeBase.chunk_* 为空时回退；仅影响新上传/重处理文档
    # - RETRIEVAL_TOP_K：chroma_store.search(top_k=None) 时兜底；聊天链路以 ModelConfig.top_k 为准
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
        if "applications.wrq.models.knowledge_execution_model" not in models:
            models.append("applications.wrq.models.knowledge_execution_model")
        models.append("aerich.models")
        models.extend([
            'applications.wrq.knowledge_base.models.query_model',
            'applications.wrq.knowledge_base.models.term_mapping_model',
            'applications.wrq.knowledge_base.models.feedback_model',
        ])
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
    DATABASE_SSL_ENABLED: bool = Field(default=False, description="是否使用 TLS/SSL 连接 MySQL")
    DATABASE_SSL_CA: str = Field(default="", description="MySQL CA 证书路径；为空时仅加密、不校验证书")
    DATABASE_SSL_CERT: str = Field(default="", description="MySQL 客户端证书路径（可选）")
    DATABASE_SSL_KEY: str = Field(default="", description="MySQL 客户端私钥路径（可选）")
    DATABASE_CONNECT_TIMEOUT: int = 15

    # Redis 配置
    REDIS_URL: str = ""
    REDIS_HOST: str = Field(default="", description="Redis主机")
    REDIS_PORT: str = Field(default="", description="Redis端口")
    REDIS_USERNAME: str = Field(default="", description="Redis用户名")
    REDIS_PASSWORD: str = Field(default="", description="Redis密码")

    @model_validator(mode="after")
    def validate_env_and_assemble_urls(self) -> Self:
        for target, legacy in (("LLM_MODEL", "LLM_MODEL_NAME"),
                               ("EMBEDDING_MODEL", "EMBEDDING_MODEL_NAME"),
                               ("EMBEDDING_BINDING_HOST", "EMBEDDING_BASE_URL"),
                               ("EMBEDDING_BINDING_API_KEY", "EMBEDDING_API_KEY")):
            value = getattr(self, legacy, "")
            if value and target not in self.model_fields_set:
                setattr(self, target, value)

        if self.KNOWLEDGE_RAG_ENV_FILE:
            from dotenv import dotenv_values
            path = Path(self.KNOWLEDGE_RAG_ENV_FILE)
            if not path.is_file():
                raise ValueError("指定的 RAG 向量模型配置文件不存在")
            source = dotenv_values(path)
            # 只读取向量模型三项；不继承旧项目数据库、Redis、JWT 或文件目录。
            for target, legacy in (("EMBEDDING_API_KEY", "EMBEDDING_BINDING_API_KEY"),
                                   ("EMBEDDING_BASE_URL", "EMBEDDING_BINDING_HOST"),
                                   ("EMBEDDING_MODEL_NAME", "EMBEDDING_MODEL")):
                if not getattr(self, target):
                    setattr(self, target, source.get(target) or source.get(legacy) or "")
        if not self.AUTH_SECRET_KEY or len(self.AUTH_SECRET_KEY) < 64:
            raise ValueError("AUTH_SECRET_KEY 配置为空或长度少于64位，请检查.env文件或环境变量")

        for field_name in ("DATABASE_USERNAME", "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} 配置为空，请检查.env文件或环境变量")

        Path(self.OUTPUT_UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.OUTPUT_DATAGRAM_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.CHROMA_DIR).mkdir(parents=True, exist_ok=True)

        return self.assemble_connection_urls()

    def assemble_connection_urls(self) -> Self:
        db_user = quote_plus(self.DATABASE_USERNAME)
        db_password = quote_plus(self.DATABASE_PASSWORD)
        ssl_query = "&ssl=true" if self.DATABASE_SSL_ENABLED else ""
        self.DATABASE_URL = (
            f"mysql://{db_user}:{db_password}@{self.DATABASE_HOST}:"
            f"{self.DATABASE_PORT}/{self.DATABASE_NAME}"
            f"?charset=utf8mb4&time_zone=+08:00{ssl_query}"
        )
        ssl_options: Dict[str, Any] | None = None
        if self.DATABASE_SSL_ENABLED:
            # asyncmy 需要非空 ssl 字典才会发起 TLS 握手。老师提供 CA 时执行证书校验；
            # 未提供 CA 时仍加密链路，但无法校验服务器身份。
            ssl_options = {"verify_mode": bool(self.DATABASE_SSL_CA)}
            if self.DATABASE_SSL_CA:
                ssl_options.update({"ca": self.DATABASE_SSL_CA, "check_hostname": True})
            if self.DATABASE_SSL_CERT:
                ssl_options["cert"] = self.DATABASE_SSL_CERT
            if self.DATABASE_SSL_KEY:
                ssl_options["key"] = self.DATABASE_SSL_KEY
        credentials = {
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
        }
        # WRQ云库wait_timeout=300，避免复用已断开的TLS空闲连接。
        from applications.wrq.database import mysql_connection_options
        credentials.update(mysql_connection_options())
        if ssl_options is not None:
            credentials["ssl"] = ssl_options
        self.DATABASE_CONNECTIONS = {
            "default": {
                "engine": "tortoise.backends.mysql",
                "credentials": credentials,
            }
        }

        for directory in (self.OUTPUT_LOGS_DIR, self.OUTPUT_UPLOAD_DIR, self.OUTPUT_DATAGRAM_DIR):
            Path(directory).mkdir(parents=True, exist_ok=True)
        if self.REDIS_PASSWORD:
            self.REDIS_URL = self.build_redis_url(db=0)
        return self

    @property
    def upload_path(self) -> Path:
        return Path(self.OUTPUT_UPLOAD_DIR)

    @property
    def datagram_path(self) -> Path:
        return Path(self.OUTPUT_DATAGRAM_DIR)

    @property
    def chroma_path(self) -> Path:
        return Path(self.CHROMA_DIR)

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

    # 所有环境默认关闭启动迁移，Linux 生产环境同样遵守此开关。
    # 表结构变更应通过审核后的显式迁移执行，不能依赖启动服务自动改表。
    @property
    def aerich_should_run_on_startup(self) -> bool:
        return self.DATABASE_AUTO_MIGRATION


@lru_cache(maxsize=1)
def get_project_config() -> ProjectConfig:
    return ProjectConfig()


PROJECT_CONFIG = get_project_config()
