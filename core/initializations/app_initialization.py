# -*- coding: utf-8 -*-
import os
import shutil
import sys
import traceback
from typing import Dict, Any

from aerich import Command
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from tortoise import Tortoise
from tortoise.contrib.fastapi import register_tortoise
from tortoise.exceptions import DoesNotExist

from configure import PROJECT_CONFIG, LOGGER
from core.exceptions.http_exceptions import (
    request_validation_exception_handler,
    response_validation_exception_handler,
    http_exception_handler,
    null_point_exception_handler,
    app_exception_handler,
)
from core.middlewares.app_middleware import logging_middleware
from core.middlewares.auth_middleware import auth_middleware
from core.middlewares.request_context_middleware import request_context_middleware
from services import DependAuth

# 离线内置的 swagger-ui / redoc 静态资源目录（随项目分发, 无网环境可用;
# 不放在 web-heroui/dist 内是为了避免被 vite build 的 emptyOutDir 清空）
SWAGGER_VENDOR_DIR = os.path.join(
    PROJECT_CONFIG.PROJECT_ROOT, "static_vendor", "swagger"
)


async def register_database(app: FastAPI) -> None:
    config: Dict[str, Any] = {
        "connections": PROJECT_CONFIG.DATABASE_CONNECTIONS,
        "apps": {
            "models": {
                "models": PROJECT_CONFIG.APPLICATIONS_MODELS,
                "default_connection": "default"
            }
        },
        "use_tz": False,
        "timezone": "Asia/Shanghai",
    }
    register_tortoise(
        app=app,
        config=config,
        generate_schemas=False,
        add_exception_handlers=PROJECT_CONFIG.SERVER_DEBUG,
    )

    # 开发环境关闭迁移时完全不触碰 aerich（避免扫描旧格式迁移文件报错阻断启动）
    if not PROJECT_CONFIG.aerich_should_run_on_startup:
        LOGGER.warning(
            "跳过 Aerich 数据迁移指令: \n"
            f"操作系统: {PROJECT_CONFIG.SERVER_SYSTEM}, \n"
            f"调试开关: {PROJECT_CONFIG.SERVER_DEBUG}, \n"
            f"迁移开关: {PROJECT_CONFIG.DATABASE_AUTO_MIGRATION}, \n"
            f"生产环境(Linux操作系统)始终执行迁移指令, 不提供关闭选项; "
            f"开发环境(Windows操作系统)仅当显示打开[DATABASE_AUTO_MIGRATION]时执行迁移指令。"
        )
        # register_tortoise 在自定义 lifespan 内部调用时, 其包裹的 orm_lifespan 本次启动不会执行,
        # 原本由 aerich 的 command.init() 负责初始化 Tortoise 连接。跳过 aerich 后需显式初始化,
        # 否则后续 init_database_table / 模型查询会报 default_connection 为 None。
        await Tortoise.init(config=config)
        # 依据模型定义补齐缺失表(CREATE TABLE IF NOT EXISTS, 不影响已存在表),
        # 使新增模型(如 term_mapping 两张表)无需 aerich 迁移即可建表并被读写。
        await Tortoise.generate_schemas(safe=True)
        LOGGER.info("已跳过 Aerich, 改为直接初始化 Tortoise 连接并按模型补齐缺失数据表")
        return

    # 确保迁移目录存在
    if not os.path.exists(PROJECT_CONFIG.MIGRATION_DIR):
        os.makedirs(PROJECT_CONFIG.MIGRATION_DIR)

    # 初始化Aerich命令
    command = Command(
        app='models',
        tortoise_config=config,
        location=PROJECT_CONFIG.MIGRATION_DIR,
    )

    # 初始化数据库和迁移
    try:
        # 当 safe 设置为 True 时，如果数据库中已经存在 Aerich 所需的迁移表（通常是 aerich 表），init_db 方法不会尝试去重新创建这些表，避免因为表已存在而抛出错误。
        # 当 safe 设置为 False 时，如果数据库中已经存在 Aerich 所需的迁移表，init_db 方法会尝试重新创建这些表，这可能会导致现有表被删除并重新创建，从而丢失表中的数据。
        await command.init_db(safe=True)
    except FileExistsError:
        pass

    await command.init()

    # 生成迁移文件
    try:
        await command.migrate(name="auto_migrate")
    except AttributeError as e:
        LOGGER.error(f"无法从数据库中检索模型历史记录, 请检查[migration]与[aerich]表记录是否一致: {e}\n错误回溯: {traceback.format_exc()}")
        if PROJECT_CONFIG.aerich_should_run_on_startup:
            shutil.rmtree(PROJECT_CONFIG.MIGRATION_DIR)
            await command.init_db(safe=True)
        else:
            raise RuntimeError("数据库迁移元数据与本地[migration]不一致, 无法进行迁移, 请手工修复或从备份恢复后再启动应用")

    # 应用迁移
    await command.upgrade(run_in_transaction=True)


# 注册异常处理器
def register_exceptions(app: FastAPI) -> None:
    # 当 FastAPI 在解析和验证请求数据时发现问题，会触发 RequestValidationError 异常
    app.add_exception_handler(
        exc_class_or_status_code=RequestValidationError,
        handler=request_validation_exception_handler
    )
    # 当 FastAPI 在解析和验证响应数据时发现问题，会触发 ResponseValidationError 异常
    app.add_exception_handler(
        exc_class_or_status_code=ResponseValidationError,
        handler=response_validation_exception_handler
    )
    # 当发生 HTTP 相关的异常时，如 403 禁止访问、404 未找到等，会触发 HTTPException 异常
    app.add_exception_handler(
        exc_class_or_status_code=HTTPException,
        handler=http_exception_handler
    )
    # 当使用 Tortoise ORM 进行数据库查询时，如果查询结果为空，会触发 DoesNotExist 异常
    app.add_exception_handler(
        exc_class_or_status_code=DoesNotExist,
        handler=null_point_exception_handler
    )
    # 当发生未被其他特定异常处理器处理的异常时，会触发此函数
    app.add_exception_handler(IOError, app_exception_handler)
    app.add_exception_handler(OSError, app_exception_handler)
    app.add_exception_handler(KeyError, app_exception_handler)
    app.add_exception_handler(ValueError, app_exception_handler)
    app.add_exception_handler(IndexError, app_exception_handler)
    app.add_exception_handler(TypeError, app_exception_handler)
    app.add_exception_handler(MemoryError, app_exception_handler)
    app.add_exception_handler(ImportError, app_exception_handler)
    app.add_exception_handler(TimeoutError, app_exception_handler)
    app.add_exception_handler(RuntimeError, app_exception_handler)
    app.add_exception_handler(AttributeError, app_exception_handler)
    app.add_exception_handler(FileExistsError, app_exception_handler)
    app.add_exception_handler(FileNotFoundError, app_exception_handler)
    app.add_exception_handler(NotADirectoryError, app_exception_handler)
    app.add_exception_handler(DoesNotExist, app_exception_handler)
    app.add_exception_handler(
        exc_class_or_status_code=Exception,
        handler=app_exception_handler
    )


def register_middlewares(app: FastAPI):
    # 注册 CORS 中间件，CORS（跨域资源共享）中间件用于处理跨域请求，允许不同域名的客户端访问服务器资源
    app.add_middleware(
        CORSMiddleware,
        allow_origins=PROJECT_CONFIG.CORS_ORIGINS,
        allow_credentials=PROJECT_CONFIG.CORS_ALLOW_CREDENTIALS,
        allow_methods=PROJECT_CONFIG.CORS_ALLOW_METHODS,
        allow_headers=PROJECT_CONFIG.CORS_ALLOW_HEADERS,
        expose_headers=PROJECT_CONFIG.CORS_EXPOSE_METHODS,
        max_age=PROJECT_CONFIG.CORS_MAX_AGE,
    )
    # 注册 HTTP 请求中间件
    app.middleware('http')(auth_middleware)
    # 先做认证拦截，再做审计日志记录
    app.middleware('http')(logging_middleware)
    # 后做日志追溯链
    app.middleware('http')(request_context_middleware)

    # 离线 vendor 资源强制再验证: StaticFiles 不带 Cache-Control, 浏览器按启发式
    # 缓存长期使用旧副本——vendor 更新后客户端仍加载旧文件（表现为"改过还报旧错"）。
    # no-cache 每次再验证, ETag 未变即 304, 开销可忽略, 保证 vendor 更新即时生效。
    @app.middleware("http")
    async def swagger_assets_no_cache(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/swagger-assets/"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def register_routers(app: FastAPI) -> None:
    # 挂载静态文件
    app.mount("/static", StaticFiles(directory=PROJECT_CONFIG.STATIC_DIR), name="static")
    # 离线接口文档静态资源（Swagger UI / ReDoc 本地 vendor, 无网环境可用）。
    # 必须挂在 /swagger-assets 下: 前端各层反向代理（vite dev / server.js /
    # nginx）只转发该前缀到后端, /static 会被前端 SPA 兜底返回 index.html,
    # 使 /docs 报 "Unexpected token '<'"（详见 static_vendor/swagger/README.md）。
    if os.path.isdir(SWAGGER_VENDOR_DIR):
        app.mount(
            "/swagger-assets",
            StaticFiles(directory=SWAGGER_VENDOR_DIR),
            name="swagger-assets",
        )
    else:
        LOGGER.warning(f"离线文档资源目录不存在, 接口文档静态资源不可用: {SWAGGER_VENDOR_DIR}")
    app.openapi_version = PROJECT_CONFIG.APP_OPENAPI_VERSION
    swagger_modules = sys.modules["fastapi.openapi.docs"].get_swagger_ui_html.__kwdefaults__
    swagger_modules["swagger_js_url"] = PROJECT_CONFIG.APP_OPENAPI_JS_URL
    swagger_modules["swagger_css_url"] = PROJECT_CONFIG.APP_OPENAPI_CSS_URL
    swagger_modules["swagger_favicon_url"] = PROJECT_CONFIG.APP_OPENAPI_FAVICON_URL
    redoc_modules = sys.modules["fastapi.openapi.docs"].get_redoc_html.__kwdefaults__
    redoc_modules["redoc_js_url"] = PROJECT_CONFIG.APP_OPENAPI_JS_URL_REDOC
    redoc_modules["redoc_favicon_url"] = PROJECT_CONFIG.APP_OPENAPI_FAVICON_URL_REDOC

    # 导入路由蓝图
    from applications.base.views import base_public, base_secure, router_secure, audit_secure
    from applications.user.views import user_public_router, user_secure_router
    from applications.example.views import example_category_router, example_product_router
    from applications.test_case_generate.views import test_case_generate_router
    from applications.zhoushengjie.views import case_recommendation_router
    from applications.ticket_review.views import ticket_review_router
    from applications.code_server_ide.views import code_server_ide_router
    from applications.jiayueyang.views import rag_public_router, rag_secure_router

    # 挂在路由蓝图
    app.include_router(router=base_public, prefix="/base", tags=["基础服务"])
    app.include_router(router=base_secure, prefix="/base", tags=["基础服务"], dependencies=[DependAuth])
    app.include_router(router=audit_secure, prefix="/base", tags=["基础服务-审计模块"], dependencies=[DependAuth])
    app.include_router(router=router_secure, prefix="/base", tags=["基础服务-路由模块"], dependencies=[DependAuth])
    app.include_router(router=user_public_router, prefix="/user", tags=["用户服务"])
    app.include_router(router=user_secure_router, prefix="/user", tags=["用户服务"], dependencies=[DependAuth])
    app.include_router(router=example_category_router, prefix="/example", tags=["示例服务-商品分类"], dependencies=[DependAuth])
    app.include_router(router=example_product_router, prefix="/example", tags=["示例服务-商品模型"], dependencies=[DependAuth])
    app.include_router(router=case_recommendation_router, prefix="/case-recommendation", tags=["用例推荐"])
    app.include_router(router=test_case_generate_router, prefix="/testCaseGen", tags=["测试用例生成"])
    app.include_router(
        router=test_case_generate_router,
        prefix="/test-case-gen",
        tags=["测试用例生成（兼容路径）"],
        include_in_schema=False,
    )
    # Keep the imported backends' public URL contracts unchanged.
    app.include_router(router=ticket_review_router)
    app.include_router(router=code_server_ide_router, prefix="/claudeEngineering")
    # jiayueyang RAG 保持合入前的 /api URL 契约。该模块原先无用户体系，
    # 因此先按公开路由挂载；若后续接入统一用户，可在此增加 DependAuth。
    app.include_router(router=rag_public_router, prefix="/api", tags=["RAG-文档智能解析与问答"])
    app.include_router(router=rag_secure_router, prefix="/api", tags=["RAG-文档智能解析与问答"])

    from applications.agent.views import mcp_servers_router, skills_router
    from applications.conversation.views import chat_router, history_router
    from applications.knowledge_base.views import knowledge_router
    from applications.model_config.views import model_router

    app.include_router(router=chat_router, prefix="/chat", tags=["RAG-对话"], dependencies=[DependAuth])
    app.include_router(router=history_router, prefix="/conversations", tags=["RAG-历史"], dependencies=[DependAuth])
    app.include_router(router=knowledge_router, prefix="/knowledge-bases", tags=["RAG-知识库"], dependencies=[DependAuth])
    app.include_router(router=model_router, prefix="/model-configs", tags=["RAG-模型配置"], dependencies=[DependAuth])
    app.include_router(router=skills_router, prefix="/skills", tags=["RAG-Agent技能"], dependencies=[DependAuth])
    app.include_router(router=mcp_servers_router, prefix="/mcp-servers", tags=["RAG-MCP服务"], dependencies=[DependAuth])

    from applications.task_center.views import task_center_router
    app.include_router(router=task_center_router, prefix="/task-center", tags=["任务中心"], dependencies=[DependAuth])
