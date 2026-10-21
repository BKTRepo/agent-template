# -*- coding: utf-8 -*-
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute
from tortoise import Tortoise
from tortoise.exceptions import DBConnectionError

from core.initializations import (
    register_database,
    register_exceptions,
    register_middlewares,
    register_routers,
)
from core.responses import SuccessResponse

try:
    from configure import PROJECT_CONFIG, ROUTER_SUMMARY, ROUTER_TAGS
except ImportError:
    from core.exceptions import NotImplementedException

    raise NotImplementedException(message="导入依赖配置失败,请检查 configure.project_config.py 文件")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        try:
            await register_database(app)
        except DBConnectionError as exc:
            raise RuntimeError(f"数据库连接失败，请检查连接配置: {exc}") from exc

        for route in app.routes:
            if isinstance(route, APIRoute):
                ROUTER_SUMMARY[route.path] = route.summary
                ROUTER_TAGS[route.path] = route.tags
        yield
    finally:
        await Tortoise.close_connections()


app = FastAPI(
    title=PROJECT_CONFIG.APP_TITLE,
    description=PROJECT_CONFIG.APP_DESCRIPTION,
    version=PROJECT_CONFIG.APP_VERSION,
    docs_url=PROJECT_CONFIG.APP_DOCS_URL,
    redoc_url=PROJECT_CONFIG.APP_REDOC_URL,
    openapi_url=PROJECT_CONFIG.APP_OPENAPI_URL,
    debug=PROJECT_CONFIG.SERVER_DEBUG,
    lifespan=lifespan,
)

register_exceptions(app)
register_middlewares(app)
register_routers(app)


@app.get("/", summary="root", tags=["基础服务"])
async def root():
    return SuccessResponse(message="FastAPI Applications Started Successfully!")


@app.get("/health", summary="健康检查", tags=["基础服务"])
async def health_check():
    return {"status": "ok", "version": PROJECT_CONFIG.APP_VERSION, "orm": "tortoise-orm"}


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(
        app=PROJECT_CONFIG.SERVER_APP,
        host=PROJECT_CONFIG.SERVER_HOST,
        port=PROJECT_CONFIG.SERVER_PORT,
        reload=PROJECT_CONFIG.SERVER_DEBUG,
        reload_delay=PROJECT_CONFIG.SERVER_DELAY,
        reload_excludes=PROJECT_CONFIG.SERVER_RELOAD_EXCLUDES,
        log_config=None,
        log_level=None,
    )
