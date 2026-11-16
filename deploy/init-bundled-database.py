"""Initialize the MySQL instance included in the offline Compose deployment."""
import asyncio
import os

from tortoise import Tortoise

from applications.knowledge_base.models.knowledge_base_model import KnowledgeTag
from applications.user.models.user_model import User
from applications.wrq.agent.models.agent_model import DeveloperSkillClass, ResourceCategory
from applications.wrq.database import wrq_connections
from configure import PROJECT_CONFIG
from services import get_password_hash


async def main():
    if PROJECT_CONFIG.DATABASE_HOST != "mysql":
        raise RuntimeError("仅支持初始化 Compose 自带的 MySQL")
    username = os.environ.get("PLATFORM_ADMIN_USERNAME", "admin")
    password = os.environ.get("PLATFORM_ADMIN_PASSWORD", "")
    if not username or len(username) > 10 or len(password) < 12:
        raise RuntimeError("请设置管理员用户名（最多 10 字符）和至少 12 字符的初始密码")
    await Tortoise.init(config={
        "connections": wrq_connections(PROJECT_CONFIG.DATABASE_CONNECTIONS),
        "apps": {"models": {"models": PROJECT_CONFIG.APPLICATIONS_MODELS, "default_connection": "default"}},
        "use_tz": False,
        "timezone": "Asia/Shanghai",
    })
    try:
        await Tortoise.generate_schemas(safe=True)
        class_names = ("历史缺陷案例推荐", "智能用例生成", "测试数据构造", "测试要点生成", "测试报告生成", "UI自动化脚本生成")
        for key, name in enumerate(class_names, 1):
            await DeveloperSkillClass.get_or_create(id=key, defaults={"name": name, "is_enabled": True})
        for code, label in (("reference", "参考资料"), ("template", "模板"), ("asset", "静态资源"), ("script", "脚本")):
            await ResourceCategory.get_or_create(code=code, defaults={"name": label, "is_enabled": True})
        for code, label, order in (("general", "通识类", 10), ("custom", "自定义", 20)):
            await KnowledgeTag.get_or_create(code=code, defaults={"name": label, "is_enabled": True, "sort_order": order})
        if not await User.filter(username=username).exists():
            await User.create(username=username, password=get_password_hash(password), alias="系统管理员",
                              email=f"{username}@platform.invalid", is_active=True, is_superuser=True)
        print("数据库基础表、字典和初始管理员已就绪")
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
