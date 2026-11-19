from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import ValidationError
from core.responses import SuccessResponse
from applications.wrq.auth import DependAuth
from applications.wrq.http import WrqRoute
from applications.wrq.agent.schemas.skill_import_schema import ImportManifest, ImportConfirm, ImportRestart, ImportNameCheck
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.agent.services.skill_import_service import SkillImportService, import_limits

skill_import = APIRouter(route_class=WrqRoute)
service = SkillImportService()


@skill_import.get('/import/get-limits', summary='技能导入-查询上传限制')
async def limits(current_user=DependAuth):
    return SuccessResponse(data=import_limits())


@skill_import.post('/import/prepare', summary='技能导入-上传并校验技能文件、目录或ZIP')
async def prepare(manifest: str = Form(...), files: list[UploadFile] = File(...), current_user=DependAuth):
    try:
        parsed = ImportManifest.model_validate_json(manifest)
    except ValidationError as exc:
        raise DeveloperError('上传清单格式无效，请重新选择文件') from exc
    return SuccessResponse(data=await service.prepare(files, parsed, current_user))


@skill_import.post('/import/confirm', summary='技能导入-确认归属并逐项创建草稿')
async def confirm(data: ImportConfirm, current_user=DependAuth):
    return SuccessResponse(data=await service.confirm(data, current_user))


@skill_import.post('/import/stage', summary='技能导入-上传校验抽取到系统临时目录，暂不落库')
async def stage(manifest: str = Form(...), files: list[UploadFile] = File(...), current_user=DependAuth):
    try:
        parsed = ImportManifest.model_validate_json(manifest)
    except ValidationError as exc:
        raise DeveloperError('上传清单格式无效，请重新选择文件') from exc
    return SuccessResponse(data=await service.prepare(files, parsed, current_user, defer_persistence=True))


@skill_import.post('/import/discard', summary='技能导入-移除本人临时上传文件，不删除正式技能')
async def discard(data: ImportRestart, current_user=DependAuth):
    await service.discard(data.import_id, current_user)
    return SuccessResponse(data={'removed': True})


@skill_import.post('/import/check-names', summary='技能导入-填写信息时检查名称重复并排除当前技能')
async def check_names(data: ImportNameCheck, current_user=DependAuth):
    return SuccessResponse(data=await service.check_names(data, current_user))


@skill_import.post('/import/restart', summary='技能导入-返回编辑并保留已导入技能的唯一编号')
async def restart(data: ImportRestart, current_user=DependAuth):
    return SuccessResponse(data=await service.restart(data.import_id, current_user))


@skill_import.get('/import/status', summary='技能导入-查询本人批次结果')
async def status(import_id: str = Query(..., pattern=r'^[0-9a-f]{32}$'), current_user=DependAuth):
    result = SuccessResponse(data=await service.status(import_id, current_user))
    result.headers['Cache-Control'] = 'no-store'
    return result
