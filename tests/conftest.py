"""仅用于隔离测试：不读取生产配置，不连接 MySQL/Redis/模型服务。"""
import atexit
import os
from pathlib import Path
import tempfile

import pytest_asyncio
from tortoise import Tortoise

_temporary = tempfile.TemporaryDirectory(prefix="skill-package-tests-")
atexit.register(_temporary.cleanup)
for name, value in {
    "AUTH_SECRET_KEY": "skill-package-isolated-test-secret-" * 3,
    "DATABASE_HOST": "127.0.0.1", "DATABASE_PORT": "3306",
    "DATABASE_USERNAME": "test", "DATABASE_NAME": "test",
    "OUTPUT_UPLOAD_DIR": str(Path(_temporary.name) / "uploads"),
    "OUTPUT_LOGS_DIR": str(Path(_temporary.name) / "logs"),
    "OUTPUT_DATAGRAM_DIR": str(Path(_temporary.name) / "datagram"),
    "CHROMA_DIR": str(Path(_temporary.name) / "chroma"),
    "SKILL_BUILD_DIR": str(Path(_temporary.name) / "builds"),
    "KNOWLEDGE_TASK_MODE": "inline",
}.items():
    os.environ[name] = value

# 项目日志处理器会创建文件和锁文件，但不会创建父目录。
Path(os.environ["OUTPUT_LOGS_DIR"]).mkdir(parents=True, exist_ok=True)


@pytest_asyncio.fixture
async def database():
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": [
        "applications.user.models.user_model",
        "applications.wrq.agent.models.agent_model",
        "applications.wrq.knowledge_base.models.knowledge_base_model",
    ]})
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()
