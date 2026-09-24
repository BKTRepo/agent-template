from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.routing import APIRoute
from tortoise import Tortoise
from tortoise.exceptions import DBConnectionError

from applications.code_server_ide.database import (
    is_database_initialized as is_ide_database_initialized,
)
from applications.code_server_ide.lifecycle import start_code_server_ide, stop_code_server_ide
from applications.ticket_review.lifecycle import start_ticket_review, stop_ticket_review
from applications.ticket_review.services.db1_pool import is_db1_pool_initialized
from applications.ticket_review.services.db2_pool import is_db2_pool_initialized
from configure import PROJECT_CONFIG, ROUTER_SUMMARY, ROUTER_TAGS
from configure import LOGGER

from .app_initialization import register_database
from .data_initialization import init_database_table


async def start_application_modules(app: FastAPI) -> None:
    """Start the main database and registered application modules."""
    app.state.shutting_down = False
    app.state.ticket_review_started = False
    app.state.code_server_ide_started = False
    try:
        await register_database(app)
    except DBConnectionError as exc:
        raise RuntimeError(f"数据库连接失败，请检查主机地址是否可达: {exc}") from exc

    await init_database_table(app)

    if PROJECT_CONFIG.TICKET_REVIEW_ENABLED:
        try:
            await start_ticket_review(app)
        except Exception as exc:
            app.state.ticket_review_started = False
            LOGGER.warning(f"ticket_review 模块启动失败（数据库未配置？），不影响其他模块: {exc}")
    else:
        app.state.ticket_review_started = False
        LOGGER.info("ticket_review 模块已通过 TICKET_REVIEW_ENABLED=False 关闭，跳过启动")

    if PROJECT_CONFIG.CODE_SERVER_IDE_ENABLED:
        try:
            await start_code_server_ide(app)
        except Exception as exc:
            app.state.code_server_ide_started = False
            LOGGER.warning(f"code_server_ide 模块启动失败（数据库未配置？），不影响其他模块: {exc}")
    else:
        app.state.code_server_ide_started = False
        LOGGER.info("code_server_ide 模块已通过 CODE_SERVER_IDE_ENABLED=False 关闭，跳过启动")

    # RAG 启动巡检与术语索引依赖主库，必须在数据库初始化后执行。
    # 两项均为可恢复的辅助初始化，失败时降级而不阻断其他已合并模块启动。
    try:
        from applications.jiayueyang.services.rag_service import RagDocumentService

        await RagDocumentService().sweep_stale_documents()
        app.state.jiayueyang_rag_started = True
    except Exception as exc:
        app.state.jiayueyang_rag_started = False
        LOGGER.warning(f"RAG 启动巡检失败，不影响其他模块启动: {exc}")

    try:
        from applications.jiayueyang.rag.query_rewriter import load_all_indices

        await load_all_indices()
    except Exception as exc:
        LOGGER.warning(f"RAG 术语库索引加载失败，将在首次查询时重试: {exc}")


async def stop_application_modules(app: FastAPI) -> None:
    """Stop application modules in reverse order and close the main ORM."""
    app.state.shutting_down = True
    try:
        if getattr(app.state, "code_server_ide_started", False):
            await stop_code_server_ide(app)
    finally:
        try:
            if getattr(app.state, "ticket_review_started", False):
                await stop_ticket_review(app)
        finally:
            await Tortoise.close_connections()


def application_health(app: FastAPI) -> dict[str, Any]:
    worker_error = getattr(app.state, "ticket_review_worker_error", None)
    status = "ok" if not worker_error else "degraded"
    return {
        "status": status,
        "modules": {
            "test_case_generate": {
                "registered": True,
                "executor": "celery",
                "outputDirectory": PROJECT_CONFIG.TEST_CASE_OUTPUT_DIR,
            },
            "ticket_review": {
                "started": getattr(app.state, "ticket_review_started", False),
                "db1": is_db1_pool_initialized(),
                "db2": is_db2_pool_initialized(),
                "workerError": worker_error,
            },
            "code_server_ide": {
                "started": getattr(app.state, "code_server_ide_started", False),
                "database": is_ide_database_initialized(),
            },
            "jiayueyang_rag": {
                "registered": True,
                "started": getattr(app.state, "jiayueyang_rag_started", False),
                "vectorBackend": PROJECT_CONFIG.VECTOR_BACKEND,
            },
        },
    }


@asynccontextmanager
async def application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        await start_application_modules(app)
        for route in app.routes:
            if isinstance(route, APIRoute):
                ROUTER_SUMMARY[route.path] = route.summary
                ROUTER_TAGS[route.path] = route.tags
        yield
    finally:
        await stop_application_modules(app)
