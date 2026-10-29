"""完整项目本地启动入口：保留全部路由和中间件，禁止启动迁移及用户初始化。

运行：python -m applications.wrq.full_backend
此入口不替换公共鉴权，也不提供新的 token 签发接口。
"""
import asyncio
import sys
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from configure import LOGGER, PROJECT_CONFIG, ROUTER_SUMMARY, ROUTER_TAGS
from applications.wrq.database import wrq_connections
from tortoise import Tortoise, connections


@asynccontextmanager
async def lifespan(app):
    if PROJECT_CONFIG.aerich_should_run_on_startup:
        raise RuntimeError("完整项目本地启动要求关闭 DATABASE_AUTO_MIGRATION")
    try:
        await Tortoise.init(config={
            "connections": wrq_connections(PROJECT_CONFIG.DATABASE_CONNECTIONS),
            "apps": {"models": {
                "models": PROJECT_CONFIG.APPLICATIONS_MODELS,
                "default_connection": "default",
            }},
            "use_tz": False,
            "timezone": "Asia/Shanghai",
        })
        database = connections.get("default")
        await database.execute_query("SELECT 1")
        _, rows = await database.execute_query(
            "SELECT COUNT(*) AS present FROM information_schema.tables "
            "WHERE table_schema=DATABASE() AND table_name='keenrobot_user'"
        )
        if not rows[0]["present"]:
            LOGGER.warning(
                "完整项目全部接口已加载；未初始化用户或迁移表。"
                "keenrobot_user 不存在，原项目登录签发及公共鉴权暂不可用。"
            )
        from fastapi.routing import APIRoute
        routes = [route for route in app.routes if isinstance(route, APIRoute)]
        for route in routes:
            ROUTER_SUMMARY[route.path] = route.summary
            ROUTER_TAGS[route.path] = route.tags
        LOGGER.info("完整项目已加载 {} 条业务路由；启动不改表、不造用户", len(routes))
        yield
    finally:
        await Tortoise.close_connections()


def create_app():
    # 使用整个项目的真实 app，保留用户、审计及其他同事模块。
    from backend_main import app
    app.router.lifespan_context = lifespan
    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host=PROJECT_CONFIG.SERVER_HOST,
                port=PROJECT_CONFIG.SERVER_PORT, reload=False)
