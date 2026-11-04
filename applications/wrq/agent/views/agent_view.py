# -*- coding: utf-8 -*-
import traceback

from fastapi import APIRouter, Depends, Query

from applications.wrq.agent.dependencies import get_mcp_server_crud, get_skill_crud
from applications.wrq.agent.schemas.agent_schema import (
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
    SkillCreate,
    SkillOut,
    SkillUpdate,
)
from applications.wrq.agent.services.agent_crud import McpServerCrud, SkillCrud
from applications.wrq.agent.schemas.api_request_schema import (
    SkillIdRequest, SkillUpdateBody, McpIdRequest, McpUpdateBody, business_payload,
)
from applications.wrq.agent.skill_names import SkillNameError
from applications.wrq.auth import PlatformIdentity as User
from configure import LOGGER
from core.exceptions import NotFoundException
from core.responses import FailureResponse, NotFoundResponse, SuccessResponse, ParameterResponse
from applications.wrq.auth import DependAuth, user_login_name

from applications.wrq.http import WrqRoute
skills = APIRouter(route_class=WrqRoute)
mcp_servers = APIRouter()


def name_error(exc):
    return ParameterResponse(message="请修正技能名称", data={"errors": [
        {"field": "skill_name", "reason": str(exc)}]})


@skills.get("/check-skill-name", summary="开发者中心-检查技能名称是否重复或可用")
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


@skills.get("/list-skills", summary="技能管理-查询技能列表")
async def list_skills(
        search: str = None,
        manage: bool = Query(default=False, description="管理页模式，包含已禁用项"),
        current_user: User = DependAuth,
        skill_crud: SkillCrud = Depends(get_skill_crud),
):
    try:
        items = await skill_crud.list_by_user(
            user_login_name(current_user), search=search, manage=manage
        )
        data = [SkillOut.model_validate(item).model_dump() for item in items]
        return SuccessResponse(data=data, total=len(data))
    except Exception as e:
        LOGGER.error(f"查询技能列表失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@skills.post("/create-skill", summary="技能管理-创建技能（请使用开发者中心完整表单）")
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


@skills.get("/get-skill", summary="技能管理-按编号查询技能详情")
async def get_skill(
        skill_id: int = Query(..., ge=1),
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


@skills.post("/update-skill", summary="技能管理-更新技能（请使用开发者中心完整表单）")
async def update_skill(
        data: SkillUpdateBody,
        current_user: User = DependAuth,
        skill_crud: SkillCrud = Depends(get_skill_crud),
):
    try:
        instance = await skill_crud.update_skill(data.skill_id, current_user, business_payload(data, SkillUpdate))
        return SuccessResponse(data=SkillOut.model_validate(instance).model_dump())
    except SkillNameError as exc:
        return name_error(exc)
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"更新技能失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"更新失败: {e}")


@skills.post("/delete-skill", summary="技能管理-删除技能草稿")
async def delete_skill(
        data: SkillIdRequest,
        current_user: User = DependAuth,
        skill_crud: SkillCrud = Depends(get_skill_crud),
):
    try:
        await skill_crud.delete_skill(data.skill_id, current_user)
        return SuccessResponse(message="技能已删除")
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"删除技能失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"删除失败: {e}")


@mcp_servers.get("/list-mcp-servers", summary="MCP服务管理-查询MCP服务列表")
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


@mcp_servers.post("/create-mcp-server", summary="MCP服务管理-创建MCP服务配置")
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


@mcp_servers.get("/get-mcp-server", summary="MCP服务管理-按编号查询MCP服务详情")
async def get_mcp_server(
        mcp_id: str = Query(..., min_length=1, max_length=64),
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


@mcp_servers.post("/update-mcp-server", summary="MCP服务管理-更新MCP服务配置")
async def update_mcp_server(
        data: McpUpdateBody,
        current_user: User = DependAuth,
        mcp_crud: McpServerCrud = Depends(get_mcp_server_crud),
):
    try:
        instance = await mcp_crud.update_mcp_server(data.mcp_id, current_user, business_payload(data, McpServerUpdate, "mcp_id"))
        return SuccessResponse(data=McpServerOut.model_validate(instance).model_dump())
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"更新MCP服务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"更新失败: {e}")


@mcp_servers.post("/delete-mcp-server", summary="MCP服务管理-删除MCP服务配置")
async def delete_mcp_server(
        data: McpIdRequest,
        current_user: User = DependAuth,
        mcp_crud: McpServerCrud = Depends(get_mcp_server_crud),
):
    try:
        await mcp_crud.delete_mcp_server(data.mcp_id, current_user)
        return SuccessResponse(message="MCP 服务已删除")
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"删除MCP服务失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"删除失败: {e}")
