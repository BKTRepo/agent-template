"""仅供本机前后端联调：SQLite + 现有登录/Skill 路由，不连接团队数据库或模型。"""
from contextlib import asynccontextmanager
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1] / "output" / "skill-integration"
ROOT.mkdir(parents=True, exist_ok=True)
# 独立进程配置，不修改项目 .env，不允许团队数据库配置介入本地联调。
secret_file = ROOT / "jwt-secret"
if not secret_file.exists():
    secret_file.write_text(secrets.token_hex(48), encoding="utf-8")
for key, value in {
    "AUTH_SECRET_KEY": secret_file.read_text(encoding="utf-8").strip(),
    "DATABASE_HOST": "127.0.0.1", "DATABASE_PORT": "3306",
    "DATABASE_USERNAME": "local-integration", "DATABASE_NAME": "local-integration",
    "SKILL_BUILD_DIR": str(ROOT / "builds"), "OUTPUT_UPLOAD_DIR": str(ROOT / "uploads"),
    "OUTPUT_LOGS_DIR": str(ROOT / "logs"), "CHROMA_DIR": str(ROOT / "unused-chroma"),
}.items():
    os.environ[key] = value

from fastapi import FastAPI
from tortoise import Tortoise
from applications.agent.views import skills_router
from applications.base.views.auth_view import auth_public
from applications.user.models.user_model import User
from services import get_password_hash


@asynccontextmanager
async def lifespan(app):
    await Tortoise.init(db_url=f"sqlite://{(ROOT / 'integration.sqlite3').as_posix()}", modules={"models": [
        "applications.user.models.user_model", "applications.agent.models.agent_model",
        "applications.knowledge_base.models.knowledge_base_model", "applications.base.models.audit_model",
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


app = FastAPI(title="Skill 本地联调（真实接口 / SQLite）", lifespan=lifespan)
app.include_router(auth_public, prefix="/base/auth")
app.include_router(skills_router, prefix="/skills")


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "local-skill-integration", "database": "sqlite", "model_execution": False}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8519)
