from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import ValidationError
from starlette.responses import Response

from applications.wrq.auth import DependAuth
from applications.wrq.http import WrqRoute
from applications.wrq.agent.services.skill_catalog_service import SkillCatalogService
from applications.wrq.agent.schemas.api_request_schema import CatalogTestRequest
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from core.responses import SuccessResponse

skill_catalog = APIRouter(route_class=WrqRoute)
catalog = SkillCatalogService()


@skill_catalog.post('/catalog/create-test-run', summary='技能中心-创建发布版在线测试任务并累计调用次数')
async def create_test(source: str = Form(...), documents: list[UploadFile] = File(default=[]), current_user=DependAuth):
    from applications.wrq.agent.services.catalog_test_service import create_catalog_test
    try:
        try:
            data = CatalogTestRequest.model_validate_json(source)
        except ValidationError as exc:
            raise DeveloperError('source须包含有效技能编号、构建编号、调用编号和对话输入', 422) from exc
        return success(await create_catalog_test(data, documents, current_user))
    finally:
        for document in documents:
            await document.close()


def success(data):
    result = SuccessResponse(data=data)
    result.headers['Cache-Control'] = 'no-store, max-age=0'
    return result


@skill_catalog.get('/catalog/get-metadata', summary='技能中心-查询大类、应用及维护人筛选项')
async def metadata(current_user=DependAuth):
    return success(await catalog.metadata())


@skill_catalog.get('/catalog/get-class', summary='技能中心-查询技能大类定义及模板')
async def class_detail(class_id: int = Query(..., ge=1), current_user=DependAuth):
    return success(await catalog.class_detail(class_id))


@skill_catalog.get('/catalog/list-skills', summary='技能中心-分页筛选已上线及已下线的发布实现')
async def list_skills(name: str = Query('', max_length=128), class_id: int | None = Query(None, ge=1),
                      application: str = Query('', max_length=100), maintainer: str = Query('', max_length=10),
                      page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=10), current_user=DependAuth):
    return success(await catalog.list(name=name, class_id=class_id, application=application,
                                      maintainer=maintainer, page=page, page_size=page_size))


@skill_catalog.get('/catalog/get-skill', summary='技能中心-查询实现发布版本详情')
async def detail(skill_id: int = Query(..., ge=1), current_user=DependAuth):
    return success(await catalog.detail(skill_id))


@skill_catalog.get('/catalog/get-build', summary='技能中心-查询固定发布构建及资源清单')
async def build(skill_id: int = Query(..., ge=1), build_id: str = Query(..., min_length=1, max_length=64), current_user=DependAuth):
    _, built, _ = await catalog.package(skill_id, build_id)
    # 不向目录调用者暴露服务器路径和原始构建源。
    keys = ('build_id', 'skill_id', 'name', 'version', 'files', 'source', 'skill_version_id', 'current_revision')
    return success({key: built[key] for key in keys if key in built})


@skill_catalog.get('/catalog/download-skill', summary='技能中心-下载发布版技能完整ZIP')
async def download(skill_id: int = Query(..., ge=1), build_id: str = Query(..., min_length=1, max_length=64), current_user=DependAuth):
    return Response(await catalog.download(skill_id, build_id), media_type='application/zip', headers={'Cache-Control': 'no-store'})


@skill_catalog.get('/catalog/download-resource', summary='技能中心-按发布构建清单读取在线测试资源原件')
async def resource(skill_id: int = Query(..., ge=1), build_id: str = Query(..., min_length=1, max_length=64),
                   path: str = Query(..., min_length=1, max_length=512), current_user=DependAuth):
    return Response(await catalog.resource(skill_id, build_id, path), media_type='application/octet-stream', headers={'Cache-Control': 'no-store'})
