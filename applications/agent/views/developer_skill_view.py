import traceback

from fastapi import APIRouter

from applications.agent.schemas.agent_schema import DeveloperDebugResult, DeveloperSkillForm
from applications.agent.services.developer_skill_crud import DeveloperSkillCrud
from applications.agent.skill_names import SkillNameError
from applications.user.models.user_model import User
from configure import LOGGER
from core.exceptions import NotFoundException
from core.responses import FailureResponse, NotFoundResponse, ParameterResponse, SuccessResponse
from services import DependAuth

developer_skills = APIRouter()
crud = DeveloperSkillCrud()


@developer_skills.get("/developer/metadata", summary="开发者中心-表单字典")
async def developer_skill_metadata(current_user: User = DependAuth):
    try:
        return SuccessResponse(data=await crud.metadata())
    except Exception as exc:
        LOGGER.error("开发者中心字典查询失败: %s\n%s", exc, traceback.format_exc())
        return FailureResponse(message="查询开发者中心字典失败")


@developer_skills.get("/developer/", summary="开发者中心-我的技能列表")
async def list_developer_skills(current_user: User = DependAuth):
    try:
        rows = await crud.list(current_user)
        return SuccessResponse(data=[crud.output(row, current_user) for row in rows], total=len(rows))
    except Exception as exc:
        LOGGER.error("开发者中心列表失败: %s\n%s", exc, traceback.format_exc())
        return FailureResponse(message="查询技能列表失败")


@developer_skills.post("/developer/", summary="开发者中心-新建草稿")
async def create_developer_skill(data: DeveloperSkillForm, current_user: User = DependAuth):
    try:
        return SuccessResponse(data=crud.output(await crud.create(current_user, data), current_user))
    except SkillNameError as exc:
        return ParameterResponse(message=str(exc))
    except ValueError as exc:
        return ParameterResponse(message=str(exc))
    except Exception as exc:
        LOGGER.error("开发者中心新建失败: %s\n%s", exc, traceback.format_exc())
        return FailureResponse(message="保存草稿失败")


@developer_skills.put("/developer/{skill_id}", summary="开发者中心-保存修改")
async def save_developer_skill(skill_id: str, data: DeveloperSkillForm, current_user: User = DependAuth):
    try:
        return SuccessResponse(data=crud.output(await crud.save(skill_id, current_user, data), current_user))
    except SkillNameError as exc:
        return ParameterResponse(message=str(exc))
    except NotFoundException as exc:
        return NotFoundResponse(message=exc.message)
    except Exception as exc:
        LOGGER.error("开发者中心保存失败: %s\n%s", exc, traceback.format_exc())
        return FailureResponse(message=str(exc))


@developer_skills.delete("/developer/{skill_id}", summary="开发者中心-删除草稿")
async def delete_developer_skill(skill_id: str, current_user: User = DependAuth):
    try:
        await crud.delete_draft(skill_id, current_user)
        return SuccessResponse(message="草稿已删除")
    except NotFoundException as exc:
        return NotFoundResponse(message=exc.message)
    except ValueError as exc:
        return ParameterResponse(message=str(exc))


@developer_skills.post("/developer/{skill_id}/offline", summary="开发者中心-下线技能")
async def offline_developer_skill(skill_id: str, current_user: User = DependAuth):
    try:
        return SuccessResponse(data=crud.output(await crud.offline(skill_id, current_user), current_user))
    except NotFoundException as exc:
        return NotFoundResponse(message=exc.message)
    except ValueError as exc:
        return ParameterResponse(message=str(exc))


@developer_skills.post("/developer/{skill_id}/publish", summary="开发者中心-上线技能")
async def publish_developer_skill(skill_id: str, current_user: User = DependAuth):
    try:
        return SuccessResponse(data=crud.output(await crud.publish(skill_id, current_user), current_user))
    except NotFoundException as exc:
        return NotFoundResponse(message=exc.message)
    except ValueError as exc:
        return ParameterResponse(message=str(exc))


@developer_skills.post("/developer/{skill_id}/debug-result", summary="开发者中心-登记沙箱调试结果")
async def record_developer_debug_result(skill_id: str, data: DeveloperDebugResult,
                                        current_user: User = DependAuth):
    try:
        skill = await crud.record_debug_result(skill_id, current_user, data)
        return SuccessResponse(data=crud.output(skill, current_user))
    except NotFoundException as exc:
        return NotFoundResponse(message=exc.message)
    except ValueError as exc:
        return ParameterResponse(message=str(exc))
