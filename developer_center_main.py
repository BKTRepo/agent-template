"""仅启动开发者中心所需接口的本地联调入口。

正式部署继续使用 backend_main.py；本入口避免未启用模块的可选依赖阻塞开发者中心联调。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from tortoise import Tortoise

from applications.agent.views import skills_router
from applications.knowledge_base.views import knowledge_router
from applications.base.views.auth_view import auth_public
from configure import PROJECT_CONFIG
from core.initializations.app_initialization import register_database
from core.initializations.data_initialization import init_database_table
from services import DependAuth


@asynccontextmanager
async def lifespan(app: FastAPI):
    await register_database(app)
    await init_database_table(app)
    yield
    await Tortoise.close_connections()


app = FastAPI(title="开发者中心联调服务", lifespan=lifespan)
app.include_router(auth_public, prefix="/base/auth")
app.include_router(skills_router, prefix="/skills", dependencies=[DependAuth])
app.include_router(knowledge_router, prefix="/knowledge-bases", dependencies=[DependAuth])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=PROJECT_CONFIG.SERVER_HOST, port=PROJECT_CONFIG.SERVER_PORT)
