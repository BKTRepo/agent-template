# -*- coding: utf-8 -*-
"""通用后端配置。"""
import os.path
import platform
import ssl
from functools import lru_cache
from pathlib import Path
from typing import List, Dict, Any, Literal
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
    WRQ_SANDBOX_MOCK: bool = False
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
    PLATFORM_APPLICATIONS: list[str] = ["信用卡系统", "核心系统", "ATPM", "FNP", "BLIM", "测试平台", "平台官方"]
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
