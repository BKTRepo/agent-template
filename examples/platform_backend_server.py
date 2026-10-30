"""仅本机后端联调：独立 SQLite/上传/向量目录，真实认证和真实业务 API。"""
from contextlib import asynccontextmanager
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1] / "output/platform-integration"
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / "logs").mkdir(exist_ok=True)
secret = ROOT / "jwt-secret"
if not secret.exists():
    secret.write_text(secrets.token_hex(48), encoding="utf-8")
for key, value in {
    "AUTH_SECRET_KEY": secret.read_text(encoding="utf-8").strip(),
    "DATABASE_HOST": "127.0.0.1", "DATABASE_PORT": "3306",
    "DATABASE_USERNAME": "local-only", "DATABASE_NAME": "local-only",
    "SKILL_BUILD_DIR": str(ROOT / "builds"), "OUTPUT_UPLOAD_DIR": str(ROOT / "uploads"),
    "OUTPUT_LOGS_DIR": str(ROOT / "logs"), "OUTPUT_DATAGRAM_DIR": str(ROOT / "datagram"),
    "CHROMA_DIR": str(ROOT / "chroma"), "RAG_OUTPUT_DIR": str(ROOT / "parsed"),
    "KNOWLEDGE_TASK_MODE": "inline",
}.items():
    os.environ[key] = value

from fastapi import FastAPI
from tortoise import Tortoise
from applications.wrq.agent.views import skills_router
from applications.wrq.knowledge_base.views import knowledge_router
from applications.base.views.auth_view import auth_public
from applications.user.models.user_model import User
from services import get_password_hash
from configure import PROJECT_CONFIG


@asynccontextmanager
async def lifespan(app):
    from examples.local_knowledge_migration import migrate_local_jobs
    migrate_local_jobs(ROOT / "platform.sqlite3")
    await Tortoise.init(db_url=f"sqlite://{(ROOT / 'platform.sqlite3').as_posix()}", modules={"models": [
        "applications.user.models.user_model", "applications.wrq.agent.models.agent_model",
        "applications.wrq.knowledge_base.models.knowledge_base_model", "applications.base.models.audit_model",
    ]})
    try:
        await Tortoise.generate_schemas(safe=True)
        await User.get_or_create(username="skill-dev", defaults={
            "alias": "本地联调用户", "email": "skill-dev@example.com",
            "password": get_password_hash("SkillLocal2026!"), "is_active": True, "is_superuser": False,
        })
        yield
    finally:
        await Tortoise.close_connections()


app = FastAPI(title="智能服务调度平台：Skill 与知识库后端联调", lifespan=lifespan)
app.include_router(auth_public, prefix="/base/auth")
app.include_router(skills_router, prefix="/skills")
app.include_router(knowledge_router, prefix="/knowledge-bases")


@app.get("/health")
async def health():
    return {"status": "ok", "database": "local-sqlite", "sandbox_execution": False,
            "embedding_configured": bool(PROJECT_CONFIG.EMBEDDING_API_KEY)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8520)
