"""python -m applications.wrq.main；不初始化用户，不自动迁移任何表。"""
import asyncio
import sys
from contextlib import asynccontextmanager
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from fastapi import FastAPI
from tortoise import Tortoise
from applications.wrq.agent.views import skills_router
from applications.wrq.knowledge_base.views import knowledge_router
from applications.wrq.database import wrq_connections
from configure import PROJECT_CONFIG

@asynccontextmanager
async def lifespan(app):
    # 本模块显式只初始化连接；启动不执行迁移或初始化用户。
    await Tortoise.init(config={
        'connections': wrq_connections(PROJECT_CONFIG.DATABASE_CONNECTIONS),
        'apps': {'models': {'models': PROJECT_CONFIG.APPLICATIONS_MODELS, 'default_connection': 'default'}},
        'use_tz': False, 'timezone': 'Asia/Shanghai'})
    yield
    await Tortoise.close_connections()

app=FastAPI(title='WRQ 开发者中心',lifespan=lifespan)
app.include_router(skills_router,prefix='/skills')
app.include_router(knowledge_router,prefix='/knowledge-bases')
if PROJECT_CONFIG.WRQ_SANDBOX_MOCK:
    from applications.wrq.mock_sandbox import router as mock_sandbox_router
    app.include_router(mock_sandbox_router)

@app.get('/health')
async def health():
    from tortoise import connections
    await connections.get('default').execute_query('SELECT 1')
    return {'status':'ok','module':'wrq'}

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host=PROJECT_CONFIG.SERVER_HOST,port=PROJECT_CONFIG.SERVER_PORT)
