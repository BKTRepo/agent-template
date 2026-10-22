# -*- coding: utf-8 -*-
from applications.agent.services.agent_crud import McpServerCrud, SkillCrud


async def get_skill_crud() -> SkillCrud:
    return SkillCrud()


async def get_mcp_server_crud() -> McpServerCrud:
    return McpServerCrud()
