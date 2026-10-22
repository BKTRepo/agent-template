# -*- coding: utf-8 -*-
from fastapi import APIRouter

from .agent_view import mcp_servers, skills
from .developer_skill_view import developer_skills
from .skill_package_view import skill_packages

skills_router = APIRouter()
mcp_servers_router = APIRouter()

skills_router.include_router(skills)
skills_router.include_router(developer_skills)
skills_router.include_router(skill_packages)
mcp_servers_router.include_router(mcp_servers)
