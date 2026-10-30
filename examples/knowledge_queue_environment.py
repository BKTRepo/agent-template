"""独立真实队列验证环境，不读取源项目的数据库或 Redis。"""
import asyncio
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1] / "output/knowledge-queue-integration"
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / "logs").mkdir(exist_ok=True)
secret = ROOT / "jwt-secret"
if not secret.exists(): secret.write_text(secrets.token_hex(48), encoding="utf-8")
for key, value in {
    "AUTH_SECRET_KEY": secret.read_text(encoding="utf-8"),
    "DATABASE_HOST": "127.0.0.1", "DATABASE_PORT": "3306", "DATABASE_USERNAME": "isolated", "DATABASE_NAME": "isolated",
    "REDIS_HOST": "127.0.0.1", "REDIS_PORT": "6398", "REDIS_USERNAME": "", "REDIS_PASSWORD": "",
    "OUTPUT_UPLOAD_DIR": str(ROOT / "uploads"), "OUTPUT_LOGS_DIR": str(ROOT / "logs"),
    "OUTPUT_DATAGRAM_DIR": str(ROOT / "datagram"), "SKILL_BUILD_DIR": str(ROOT / "builds"),
    "CHROMA_DIR": str(ROOT / "chroma"), "RAG_OUTPUT_DIR": str(ROOT / "parsed"),
    "KNOWLEDGE_TASK_MODE": "celery",
}.items(): os.environ[key] = value

from configure import PROJECT_CONFIG
MODELS = ["applications.user.models.user_model", "applications.wrq.agent.models.agent_model",
          "applications.wrq.knowledge_base.models.knowledge_base_model", "applications.base.models.audit_model"]
DB = ROOT / "platform.sqlite3"
PROJECT_CONFIG.DATABASE_CONNECTIONS = {"default": f"sqlite://{DB.as_posix()}"}


def install_worker_database():
    from tortoise import Tortoise
    from celery_scheduler import celery_base
    ready, lock = False, None
    async def init_local():
        nonlocal ready, lock
        if lock is None: lock = asyncio.Lock()
        async with lock:
            if not ready:
                await Tortoise.init(db_url=f"sqlite://{DB.as_posix()}", modules={"models": MODELS})
                ready = True
    celery_base.init_tortoise_orm = init_local
