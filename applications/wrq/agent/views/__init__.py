# -*- coding: utf-8 -*-
from fastapi import APIRouter

from .agent_view import mcp_servers, skills
from .developer_skill_view import developer_skills
from .skill_package_view import skill_packages

skills_router = APIRouter()
mcp_servers_router = APIRouter()

# 固定路径必须先于 /{skill_id} 这类通配路由注册，否则
# GET /skills/developer 会被当成 skill_id="developer" 处理。
skills_router.include_router(developer_skills)
skills_router.include_router(skill_packages)
skills_router.include_router(skills)
mcp_servers_router.include_router(mcp_servers)
