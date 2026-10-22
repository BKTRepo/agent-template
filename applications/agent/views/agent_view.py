# -*- coding: utf-8 -*-
import traceback

from fastapi import APIRouter, Depends, Query

from applications.agent.dependencies import get_mcp_server_crud, get_skill_crud
from applications.agent.schemas.agent_schema import (
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
    SkillCreate,
    SkillOut,
    SkillUpdate,
)
from applications.agent.services.agent_crud import McpServerCrud, SkillCrud
from applications.agent.skill_names import SkillNameError
from applications.user.models.user_model import User
from configure import LOGGER
from core.exceptions import NotFoundException
from core.responses import FailureResponse, NotFoundResponse, SuccessResponse, ParameterResponse
from services import DependAuth

skills = APIRouter()
mcp_servers = APIRouter()


def name_error(exc):
    return ParameterResponse(message="请修正技能名称", data={"errors": [
        {"field": "skill_name", "reason": str(exc)}]})


@skills.get("/name-availability", summary="开发者中心-检查技能名称是否可用")
async def check_skill_name(name: str = Query(..., max_length=128), exclude_id: str = None,
                           current_user: User = DependAuth,
                           skill_crud: SkillCrud = Depends(get_skill_crud)):
    try:
        if exclude_id:
            await skill_crud.get_skill(exclude_id, current_user)
        return SuccessResponse(data={"available": await skill_crud.name_available(name, exclude_id=exclude_id)})
    except SkillNameError as exc:
        return name_error(exc)
    except NotFoundException as exc:
        return NotFoundResponse(message=exc.message)


@skills.get("/", summary="Agent-查询技能列表")
async def list_skills(
        search: str = None,
        manage: bool = Query(default=False, description="管理页模式，包含已禁用项"),
        current_user: User = DependAuth,
        skill_crud: SkillCrud = Depends(get_skill_crud),
):
    try:
        items = await skill_crud.list_by_user(
            current_user.id, search=search, manage=manage
        )
        data = [SkillOut.model_validate(item).model_dump() for item in items]
        return SuccessResponse(data=data, total=len(data))
    except Exception as e:
        LOGGER.error(f"查询技能列表失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@skills.post("/", summary="Agent-新增技能")
async def create_skill(
        data: SkillCreate,
        current_user: User = DependAuth,
        skill_crud: SkillCrud = Depends(get_skill_crud),
):
    try:
        instance = await skill_crud.create_skill(current_user, data)
        return SuccessResponse(data=SkillOut.model_validate(instance).model_dump())
    except SkillNameError as exc:
        return name_error(exc)
    except Exception as e:
        LOGGER.error(f"创建技能失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"创建失败: {e}")


@skills.get("/{skill_id}", summary="Agent-按id查询技能详情")
async def get_skill(
        skill_id: str,
        current_user: User = DependAuth,
        skill_crud: SkillCrud = Depends(get_skill_crud),
):
    try:
        instance = await skill_crud.get_skill(skill_id, current_user)
        return SuccessResponse(data=SkillOut.model_validate(instance).model_dump())
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询技能详情失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@skills.put("/{skill_id}", summary="Agent-按id更新技能")
async def update_skill(
        skill_id: str,
        data: SkillUpdate,
        current_user: User = DependAuth,
        skill_crud: SkillCrud = Depends(get_skill_crud),
):
    try:
        instance = await skill_crud.update_skill(skill_id, current_user, data)
        return SuccessResponse(data=SkillOut.model_validate(instance).model_dump())
    except SkillNameError as exc:
        return name_error(exc)
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"更新技能失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"更新失败: {e}")


@skills.delete("/{skill_id}", summary="Agent-按id删除技能")
async def delete_skill(
        skill_id: str,
        current_user: User = DependAuth,
        skill_crud: SkillCrud = Depends(get_skill_crud),
):
    try:
        await skill_crud.delete_skill(skill_id, current_user)
        return SuccessResponse(message="技能已删除")
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"删除技能失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"删除失败: {e}")


@mcp_servers.get("/", summary="Agent-查询MCP服务列表")
async def list_mcp_servers(
        search: str = None,
        manage: bool = Query(default=False, description="管理页模式，包含已禁用项"),
        current_user: User = DependAuth,
        mcp_crud: McpServerCrud = Depends(get_mcp_server_crud),
):
    try:
        items = await mcp_crud.list_by_user(
            current_user.id, search=search, manage=manage
        )
        data = [McpServerOut.model_validate(item).model_dump() for item in items]
        return SuccessResponse(data=data, total=len(data))
    except Exception as e:
        LOGGER.error(f"查询MCP服务列表失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@mcp_servers.post("/", summary="Agent-新增MCP服务")
async def create_mcp_server(
        data: McpServerCreate,
        current_user: User = DependAuth,
        mcp_crud: McpServerCrud = Depends(get_mcp_server_crud),
):
    try:
        instance = await mcp_crud.create_mcp_server(current_user, data)
        return SuccessResponse(data=McpServerOut.model_validate(instance).model_dump())
    except Exception as e:
        LOGGER.error(f"创建MCP服务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"创建失败: {e}")


@mcp_servers.get("/{mcp_id}", summary="Agent-按id查询MCP服务详情")
async def get_mcp_server(
        mcp_id: str,
        current_user: User = DependAuth,
        mcp_crud: McpServerCrud = Depends(get_mcp_server_crud),
):
    try:
        instance = await mcp_crud.get_mcp_server(mcp_id, current_user)
        return SuccessResponse(data=McpServerOut.model_validate(instance).model_dump())
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询MCP服务详情失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@mcp_servers.put("/{mcp_id}", summary="Agent-按id更新MCP服务")
async def update_mcp_server(
        mcp_id: str,
        data: McpServerUpdate,
        current_user: User = DependAuth,
        mcp_crud: McpServerCrud = Depends(get_mcp_server_crud),
):
    try:
        instance = await mcp_crud.update_mcp_server(mcp_id, current_user, data)
        return SuccessResponse(data=McpServerOut.model_validate(instance).model_dump())
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"更新MCP服务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"更新失败: {e}")


@mcp_servers.delete("/{mcp_id}", summary="Agent-按id删除MCP服务")
async def delete_mcp_server(
        mcp_id: str,
        current_user: User = DependAuth,
        mcp_crud: McpServerCrud = Depends(get_mcp_server_crud),
):
    try:
        await mcp_crud.delete_mcp_server(mcp_id, current_user)
        return SuccessResponse(message="MCP 服务已删除")
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"删除MCP服务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"删除失败: {e}")
