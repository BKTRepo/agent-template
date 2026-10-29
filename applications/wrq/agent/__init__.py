# -*- coding: utf-8 -*-
__all__ = ["Skill", "McpServer"]


def __getattr__(name):
    # 独立生成器只需要 Schema；访问模型时才加载数据库及项目配置。
    # 保留旧的 from applications.wrq.agent import Skill, McpServer 用法。
    if name in __all__:
        from applications.wrq.agent.models import agent_model

        value = getattr(agent_model, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
