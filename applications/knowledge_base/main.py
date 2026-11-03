"""知识库独立启动入口，不自动迁移数据库或初始化用户。"""
import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from tortoise import Tortoise, connections

from applications.wrq.database import wrq_connections
from applications.knowledge_base.views import knowledge_router
from configure import PROJECT_CONFIG

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app):
    await Tortoise.init(config={
        "connections": wrq_connections(PROJECT_CONFIG.DATABASE_CONNECTIONS),
        "apps": {"models": {"models": PROJECT_CONFIG.APPLICATIONS_MODELS, "default_connection": "default"}},
        "use_tz": False,
        "timezone": "Asia/Shanghai",
    })
    try:
        yield
    finally:
        await Tortoise.close_connections()


app = FastAPI(title="知识库与文件管理", lifespan=lifespan)
app.include_router(knowledge_router, prefix="/knowledge-bases")
from applications.knowledge_base.views.conversion_view import conversion_router
app.include_router(conversion_router, prefix="/api")


@app.get("/health")
async def health():
    await connections.get("default").execute_query("SELECT 1")
    return {"status": "ok", "module": "knowledge_base"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=PROJECT_CONFIG.SERVER_HOST, port=PROJECT_CONFIG.SERVER_PORT)
