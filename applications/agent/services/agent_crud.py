# -*- coding: utf-8 -*-
from typing import List, Optional
from tortoise.exceptions import IntegrityError
from applications.agent.skill_names import SkillNameError, skill_name_key

from applications.agent.models.agent_model import McpServer, Skill
from applications.agent.schemas.agent_schema import (
    McpServerCreate,
    McpServerUpdate,
    SkillCreate,
    SkillUpdate,
)
from applications.base.services.scaffold import ScaffoldCrud
from applications.user.models.user_model import User
from core.exceptions import NotFoundException


class SkillCrud(ScaffoldCrud):
    def __init__(self):
        super().__init__(model=Skill)

    async def list_by_user(
            self, user_id: int, *, search: str = None, manage: bool = False
    ) -> List[Skill]:
        """查询技能列表；manage=True 时包含已禁用项（聊天选择器仅返回启用项）"""
        qs = self.model.filter(user_id=user_id, state__not=1)
        if not manage:
            qs = qs.filter(is_enabled=True)
        if search:
            qs = qs.filter(name__icontains=search)
        return await qs.order_by("-updated_time")

    async def get_by_id(self, skill_id: str) -> Optional[Skill]:
        return await self.model.get_or_none(id=skill_id, state__not=1)

    async def get_skill(self, skill_id: str, user: User) -> Skill:
        skill = await self.get_by_id(skill_id)
        if not skill:
            raise NotFoundException(message="技能不存在")
        self.check_access(skill, user)
        return skill

    def check_access(self, skill: Skill, user: User) -> None:
        if skill.user_id != user.id:
            raise NotFoundException(message="技能不存在")

    async def create_skill(self, user: User, data: SkillCreate) -> Skill:
        obj_dict = data.create_dict()
        obj_dict["user_id"] = user.id
        await self.require_available_name(data.name)
        try:
            return await self.create(obj_dict)
        except IntegrityError as exc:
            raise SkillNameError("技能名称已存在，请使用其他名称") from exc

    async def name_available(self, name: str, *, exclude_id: str = None, using_db=None) -> bool:
        query = self.model.filter(name_key=skill_name_key(name), state__not=1)
        if exclude_id:
            query = query.exclude(id=exclude_id)
        if using_db:
            query = query.using_db(using_db)
        return not await query.exists()

    async def require_available_name(self, name: str, *, exclude_id: str = None, using_db=None):
        if not await self.name_available(name, exclude_id=exclude_id, using_db=using_db):
            raise SkillNameError("技能名称已存在，请使用其他名称")

    async def update_skill(
            self, skill_id: str, user: User, data: SkillUpdate
    ) -> Skill:
        effective_id = data.skill_id or skill_id
        skill = await self.get_skill(effective_id, user)
        obj_dict = data.model_dump(exclude_unset=True, exclude={"skill_id"})
        if (skill.config or {}).get("parser_source"):
            if {"name", "description"}.intersection(obj_dict):
                raise SkillNameError("已生成的技能请通过完整表单保存，名称、描述、版本和包内容会同步更新")
            if "config" in obj_dict:
                reserved = {k: v for k, v in skill.config.items() if k in {"parser_revision", "latest_build_id", "parser_source"}}
                obj_dict["config"] = {**(obj_dict["config"] or {}), **reserved}
        if "name" in obj_dict:
            await self.require_available_name(obj_dict["name"], exclude_id=skill.id)
        if obj_dict:
            skill = skill.update_from_dict(obj_dict)
            try:
                await skill.save()
            except IntegrityError as exc:
                raise SkillNameError("技能名称已存在，请使用其他名称") from exc
        return skill

    async def delete_skill(self, skill_id: str, user: User) -> None:
        skill = await self.get_skill(skill_id, user)
        skill.state = 1
        await skill.save()


class McpServerCrud(ScaffoldCrud):
    def __init__(self):
        super().__init__(model=McpServer)

    async def list_by_user(
            self, user_id: int, *, search: str = None, manage: bool = False
    ) -> List[McpServer]:
        qs = self.model.filter(user_id=user_id, state__not=1)
        if not manage:
            qs = qs.filter(is_enabled=True)
        if search:
            qs = qs.filter(name__icontains=search)
        return await qs.order_by("-updated_time")

    async def get_by_id(self, mcp_id: str) -> Optional[McpServer]:
        return await self.model.get_or_none(id=mcp_id, state__not=1)

    async def get_mcp_server(self, mcp_id: str, user: User) -> McpServer:
        mcp = await self.get_by_id(mcp_id)
        if not mcp:
            raise NotFoundException(message="MCP 服务不存在")
        self.check_access(mcp, user)
        return mcp

    def check_access(self, mcp: McpServer, user: User) -> None:
        if mcp.user_id != user.id:
            raise NotFoundException(message="MCP 服务不存在")

    async def create_mcp_server(self, user: User, data: McpServerCreate) -> McpServer:
        obj_dict = data.create_dict()
        obj_dict["user_id"] = user.id
        return await self.create(obj_dict)

    async def update_mcp_server(
            self, mcp_id: str, user: User, data: McpServerUpdate
    ) -> McpServer:
        effective_id = data.mcp_id or mcp_id
        mcp = await self.get_mcp_server(effective_id, user)
        obj_dict = data.model_dump(exclude_unset=True, exclude={"mcp_id"})
        if obj_dict:
            mcp = mcp.update_from_dict(obj_dict)
            await mcp.save()
        return mcp

    async def delete_mcp_server(self, mcp_id: str, user: User) -> None:
        mcp = await self.get_mcp_server(mcp_id, user)
        mcp.state = 1
        await mcp.save()
