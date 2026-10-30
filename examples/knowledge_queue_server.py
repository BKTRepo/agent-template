"""本机 8530：真实 Celery 模式 API，配合独立 Redis 6398。"""
from examples.knowledge_queue_environment import ROOT, DB, MODELS
from contextlib import asynccontextmanager
from fastapi import FastAPI
from tortoise import Tortoise
from applications.wrq.agent.views import skills_router
from applications.wrq.knowledge_base.views import knowledge_router
from applications.base.views.auth_view import auth_public
from applications.user.models.user_model import User
from services import get_password_hash


@asynccontextmanager
async def lifespan(app):
    from examples.local_knowledge_migration import migrate_local_jobs
    migrate_local_jobs(DB)
    await Tortoise.init(db_url=f"sqlite://{DB.as_posix()}", modules={"models": MODELS})
    await Tortoise.generate_schemas(safe=True)
    await User.get_or_create(username="skill-dev", defaults={"alias": "队列验证用户", "email": "queue@example.com",
        "password": get_password_hash("SkillLocal2026!"), "is_active": True, "is_superuser": False})
    try: yield
    finally: await Tortoise.close_connections()


app = FastAPI(title="知识库真实队列本机验证", lifespan=lifespan)
app.include_router(auth_public, prefix="/base/auth")
app.include_router(skills_router, prefix="/skills")
app.include_router(knowledge_router, prefix="/knowledge-bases")


@app.get("/health")
async def health():
    return {"status": "ok", "knowledge_task_mode": "celery", "database": "isolated-sqlite", "redis_port": 6398}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8530)
