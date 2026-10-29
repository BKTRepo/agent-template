# -*- coding: utf-8 -*-
"""通用后端配置。"""
import os.path
import platform
import ssl
from functools import lru_cache
from pathlib import Path
from typing import List, Dict, Any
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self

from common import FileUtils

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
    APP_OPENAPI_URL: str = "/openapi.json"
    APP_OPENAPI_JS_URL: str = "/static/swagger-ui/swagger-ui-bundle.js"
    APP_OPENAPI_CSS_URL: str = "/static/swagger-ui/swagger-ui.css"
    APP_OPENAPI_FAVICON_URL: str = "/static/swagger-ui/favicon-32x32.png"
    APP_OPENAPI_JS_URL_REDOC: str = "/static/redoc/bundles/redoc.standalone.js"
    APP_OPENAPI_FAVICON_URL_REDOC: str = "/static/redoc/favicon.png"
    APP_OPENAPI_VERSION: str = "3.0.2"

    # 调试配置
    SERVER_APP: str = "backend_main:app"
    SERVER_HOST: str = "0.0.0.0"
    SERVER_SYSTEM: str = platform.system()
    SERVER_PORT: int = 8000
    SERVER_DEBUG: bool = SERVER_SYSTEM != "Linux"  # Windows | Linux | Darwin
    SERVER_DELAY: int = 5
    SERVER_RELOAD_EXCLUDES: List[str] = [
        "*/output/*",
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
    OUTPUT_DOCS_DIR: str = os.path.abspath(os.path.join(OUTPUT_DIR, "docs"))
    SERVICES_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "services"))
    STATIC_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "static"))
    STATIC_IMG_DIR: str = os.path.abspath(os.path.join(STATIC_DIR, "image"))
    MIGRATION_DIR: str = os.path.abspath(os.path.join(_BACKEND_PROJECT_ROOT, "migrations"))



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

    # 可直接配置 DATABASE_URL，或填写以下 MySQL 连接参数。
    DATABASE_AUTO_MIGRATION: bool = False
    DATABASE_CONNECTIONS: Dict[str, Any] = {}
    DATABASE_URL: str = ""
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 3306
    DATABASE_NAME: str = "template"
    DATABASE_USERNAME: str = ""
    DATABASE_PASSWORD: str = ""
    # 是否要求 MySQL 连接使用 TLS/SSL 加密；仅加密、不校验证书时可设为 True。
    DATABASE_SSL_ENABLED: bool = False
    # 建立 MySQL 网络连接最长等待秒数，避免数据库不可用时接口长期无响应。
    DATABASE_CONNECT_TIMEOUT: int = 15

    @model_validator(mode="after")
    def validate_env_and_assemble_urls(self) -> Self:
        if not self.AUTH_SECRET_KEY or len(self.AUTH_SECRET_KEY) < 64:
            raise ValueError("AUTH_SECRET_KEY 配置为空或长度少于64位，请检查.env文件或环境变量")

        if self.DATABASE_URL:
            self.DATABASE_CONNECTIONS = {"default": self.DATABASE_URL}
        else:
            if not self.DATABASE_USERNAME or not self.DATABASE_NAME or not self.DATABASE_HOST:
                raise ValueError("请配置 DATABASE_URL 或完整的 MySQL 连接参数")
            # 与 DBeaver 中“需要 SSL、关闭验证服务器证书”的配置保持一致。
            # 后续拿到数据库 CA 证书后，应改为校验证书的安全配置。
            mysql_ssl: bool | ssl.SSLContext = False
            if self.DATABASE_SSL_ENABLED:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                mysql_ssl = ssl_context
            db_user = quote_plus(self.DATABASE_USERNAME)
            db_password = quote_plus(self.DATABASE_PASSWORD)
            self.DATABASE_URL = (
                f"mysql://{db_user}:{db_password}@{self.DATABASE_HOST}:"
                f"{self.DATABASE_PORT}/{self.DATABASE_NAME}"
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
                        "minsize": 1,
                        "maxsize": 10,
                        "charset": "utf8mb4",
                        "connect_timeout": self.DATABASE_CONNECT_TIMEOUT,
                        "ssl": mysql_ssl,
                    },
                }
            }

        for directory in (self.OUTPUT_LOGS_DIR, self.OUTPUT_UPLOAD_DIR, self.OUTPUT_DATAGRAM_DIR):
            Path(directory).mkdir(parents=True, exist_ok=True)
        return self

    @property
    def upload_path(self) -> Path:
        return Path(self.OUTPUT_UPLOAD_DIR)

    @property
    def datagram_path(self) -> Path:
        return Path(self.OUTPUT_DATAGRAM_DIR)


@lru_cache(maxsize=1)
def get_project_config() -> ProjectConfig:
    return ProjectConfig()


PROJECT_CONFIG = get_project_config()

# FastAPI、Aerich 和管理脚本共用同一份 ORM 配置。
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
