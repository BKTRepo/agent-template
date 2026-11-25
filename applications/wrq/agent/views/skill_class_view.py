from fastapi import APIRouter, Query

from applications.wrq.auth import DependAuth
from applications.wrq.http import WrqRoute
from core.responses import SuccessResponse
from ..schemas.skill_class_schema import SkillClassCreate, SkillClassUpdate, SkillClassRemove
from ..services.skill_class_service import SkillClassService

skill_classes = APIRouter(route_class=WrqRoute)
service = SkillClassService()


def success(data):
    response = SuccessResponse(data=data)
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response


@skill_classes.get('/classes/get-metadata', summary='技能大类-查询测试阶段及可用大类字典')
async def metadata(current_user=DependAuth):
    return success(await service.metadata())


@skill_classes.get('/classes/list', summary='技能大类-分页查询全平台大类、阶段统计及本人权限')
async def list_classes(test_stage_id: int | None = Query(None, ge=1), page: int = Query(1, ge=1),
                       page_size: int = Query(10, ge=1, le=100), current_user=DependAuth):
    return success(await service.list(current_user, test_stage_id=test_stage_id, page=page, page_size=page_size))


@skill_classes.get('/classes/get', summary='技能大类-查询完整契约与模板详情')
async def detail(class_id: int = Query(..., ge=1, le=2147483647), current_user=DependAuth):
    return success(await service.detail(class_id, current_user))


@skill_classes.post('/classes/create', summary='技能大类-创建本人维护的大类草稿')
async def create(data: SkillClassCreate, current_user=DependAuth):
    return success(await service.create(data, current_user))


@skill_classes.post('/classes/update', summary='技能大类-校验本人权限和修订号后保存修改')
async def update(data: SkillClassUpdate, current_user=DependAuth):
    return success(await service.update(data, current_user))


@skill_classes.post('/classes/remove', summary='技能大类-仅本人且无关联实现时删除')
async def remove(data: SkillClassRemove, current_user=DependAuth):
    return success(await service.remove(data, current_user))


@skill_classes.post('/classes/publish', summary='技能大类-本人确认完整契约后发布，无审批流')
async def publish(data: SkillClassRemove, current_user=DependAuth):
    return success(await service.publish(data, current_user))
