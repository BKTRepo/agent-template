# -*- coding: utf-8 -*-
from fastapi import APIRouter

from .agent_view import mcp_servers, skills
from .developer_skill_view import developer_skills
from .skill_package_view import skill_packages
from .knowledge_view import router as knowledge_router

skills_router = APIRouter()
mcp_servers_router = APIRouter()

# WRQ 使用固定业务动作路径；GET 编号通过查询参数传入，POST 编号在请求体中。
skills_router.include_router(developer_skills)
skills_router.include_router(knowledge_router)
skills_router.include_router(skill_packages)
skills_router.include_router(skills)
mcp_servers_router.include_router(mcp_servers)
