# -*- coding: utf-8 -*-
from typing import List, Optional
from tortoise.exceptions import IntegrityError
from applications.wrq.agent.skill_names import SkillNameError, skill_name_key

from applications.wrq.agent.models.agent_model import McpServer, Skill
from applications.wrq.agent.schemas.agent_schema import (
    McpServerCreate,
    McpServerUpdate,
    SkillCreate,
    SkillUpdate,
)
from applications.base.services.scaffold import ScaffoldCrud
from applications.user.models.user_model import User
from core.exceptions import NotFoundException
from applications.wrq.auth import user_login_name
from applications.wrq.markdown_storage import read_markdown


class SkillCrud(ScaffoldCrud):
    def __init__(self):
        super().__init__(model=Skill)

    async def list_by_user(self, login_name, *, search=None, manage=False):
        qs = Skill.filter(create_user_login_name=login_name, state=0)
        if not manage:
            qs = qs.filter(display_status="ONLINE")
        if search:
            qs = qs.filter(name__icontains=search)
        rows = await qs.order_by("-updated_time")
        from applications.wrq.agent.models.agent_model import SkillForm
        for row in rows:
            form = await SkillForm.get_or_none(skill_version_id=row.current_version_id)
            row.config = {"description": form.description, "instructions": form.instructions,
                          "skill_markdown": read_markdown(form.skill_markdown_path)} if form else {}
        return rows

    async def get_by_id(self, skill_id):
        return await Skill.get_or_none(id=skill_id, state=0)

    async def get_skill(self, skill_id, user):
        from applications.wrq.agent.services.developer_skill_crud import DeveloperSkillCrud
        return await DeveloperSkillCrud().get(skill_id, user)

    def check_access(self, skill, user):
        if skill.create_user_login_name != user_login_name(user):
            raise NotFoundException(message="技能不存在")

    async def name_available(self, name, *, exclude_id=None, using_db=None):
        from applications.wrq.agent.services.developer_skill_crud import DeveloperSkillCrud
        return await DeveloperSkillCrud().name_available(name, exclude_id, using_db)

    async def require_available_name(self, name, *, exclude_id=None, using_db=None):
        if not await self.name_available(name, exclude_id=exclude_id, using_db=using_db):
            raise SkillNameError("该技能名称已存在，请更换")

    async def create_skill(self, user, data):
        raise SkillNameError("请使用开发者中心完整表单创建技能")

    async def update_skill(self, skill_id, user, data):
        raise SkillNameError("请使用开发者中心完整表单保存修改")

    async def delete_skill(self, skill_id, user):
        from applications.wrq.agent.services.developer_skill_crud import DeveloperSkillCrud
        await DeveloperSkillCrud().delete_draft(skill_id, user)


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
