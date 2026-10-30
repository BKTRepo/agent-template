# -*- coding: utf-8 -*-
"""
@Author  : yangkai
@Email   : 807440781@qq.com
@Project : KeenRobot
@Module  : init_model_configs.py
@DateTime: 2025/4/28 18:07
"""
"""初始化 DeepSeek 模型配置示例（直接运行脚本时使用，非 env seed）"""

import asyncio

import _bootstrap  # noqa: F401  将项目根目录加入 sys.path

from tortoise import Tortoise

from configure import PROJECT_CONFIG
from applications.user.models.user_model import User
from applications.model_config.models.model_config_model import ModelConfig

DEEPSEEK_CONFIGS = [
    {
        "config_name": "DeepSeek Chat",
        "config_desc": "通用企业知识库问答",
        "model_provider": "deepseek",
        "llm_model_name": "deepseek-chat",
        "model_thinking": False,
        "temperature": 0.7,
        "max_tokens": 4096,
        "top_p": 0.95,
        "top_k": 5,
        "score_threshold": 0.0,
        "max_history_rounds": 10,
        "is_default": True,
    },
    {
        "config_name": "DeepSeek Reasoner",
        "config_desc": "复杂推理与深度分析",
        "model_provider": "deepseek",
        "llm_model_name": "deepseek-reasoner",
        "model_thinking": True,
        "temperature": 0.7,
        "max_tokens": 4096,
        "top_p": 0.95,
        "top_k": 5,
        "score_threshold": 0.0,
        "max_history_rounds": 10,
        "is_default": False,
    },
]


def build_tortoise_config():
    return {
        "connections": PROJECT_CONFIG.DATABASE_CONNECTIONS,
        "apps": {
            "models": {
                "models": PROJECT_CONFIG.APPLICATIONS_MODELS,
                "default_connection": "default"
            }
        },
        "use_tz": False,
        "timezone": "Asia/Shanghai",
    }


async def init_model_configs():
    await Tortoise.init(config=build_tortoise_config())

    admin = await User.get_or_none(username="admin")
    if not admin:
        print("❌ Admin 账号不存在，请先运行 init_admin.py")
        await Tortoise.close_connections()
        return

    print(f"找到 admin 账号 (ID: {admin.id})")
    existing = await ModelConfig.filter(user_id=admin.id).all()

    if existing:
        print(f"发现 {len(existing)} 个已有配置，跳过创建")
    else:
        print("创建 DeepSeek 模型配置示例...")
        for item in DEEPSEEK_CONFIGS:
            config = await ModelConfig.create(user_id=admin.id, **item)
            print(f"  ✅ 创建: {config.config_name} ({config.llm_model_name})")
        print(f"\n✅ 成功创建 {len(DEEPSEEK_CONFIGS)} 个模型配置！")

    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(init_model_configs())
