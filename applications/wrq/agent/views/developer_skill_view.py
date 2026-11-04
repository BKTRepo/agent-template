import json
from fastapi import APIRouter, File, Form, Query, UploadFile
from starlette.responses import FileResponse
from applications.wrq.http import WrqRoute
from applications.wrq.agent.schemas.agent_schema import DeveloperDebugResult, DeveloperSkillForm, OfflineSkillRequest
from applications.wrq.agent.schemas.api_request_schema import (
    DeveloperSkillSaveRequest, OfflineSkillBody, RegisterDebugRunRequest,
    SkillIdRequest, business_payload,
)
from applications.wrq.agent.services.developer_skill_crud import DeveloperSkillCrud, DeveloperError
from applications.wrq.agent.services.source_service import SourceService
from core.responses import SuccessResponse
from applications.wrq.auth import DependAuth, user_login_name

developer_skills=APIRouter(route_class=WrqRoute)
crud=DeveloperSkillCrud()
sources=SourceService()

def categories_value(value):
    try:
        return json.loads(value)
    except (json.JSONDecodeError,TypeError) as exc:
        raise DeveloperError('资源用途分类必须是JSON数组') from exc


@developer_skills.get('/developer/get-current-user',summary='开发者中心-查询当前登录用户身份')
async def context(current_user=DependAuth):
    login = user_login_name(current_user)
    return SuccessResponse(data={'id':login,'login_name':login,'name':current_user.alias or current_user.username})

@developer_skills.get('/developer/get-form-metadata',summary='开发者中心-查询技能类、应用和资源用途字典')
async def metadata(current_user=DependAuth):
    result=SuccessResponse(data=await crud.metadata())
    result.headers['Cache-Control'] = 'no-store, max-age=0'
    result.headers['Pragma'] = 'no-cache'
    return result

@developer_skills.get('/developer/list-skills',summary='开发者中心-分页查询本人技能列表及调试状态')
async def list_skills(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100), current_user=DependAuth):
    # 列表用于开发者中心的刷新与分页，禁止浏览器/代理复用旧快照。
    rows,total=await crud.list(current_user,page=page,page_size=page_size)
    pages=max(1,(total+page_size-1)//page_size)
    # 删除最后一页记录后，刷新可能仍带着旧页码；回退到最后有效页，避免前端停在空白页。
    if page > pages:
        page=pages
        rows,total=await crud.list(current_user,page=page,page_size=page_size)
    result=SuccessResponse(data={'items':[await crud.output(r,current_user) for r in rows], 'total':total,
        'page':page, 'page_size':page_size, 'pages':pages})
    result.headers['Cache-Control'] = 'no-store, max-age=0'
    result.headers['Pragma'] = 'no-cache'
    return result

@developer_skills.post('/developer/create-skill-draft',summary='开发者中心-创建技能草稿')
async def create(data:DeveloperSkillForm,current_user=DependAuth):
    return SuccessResponse(data=await crud.output(await crud.create(current_user,data),current_user))

@developer_skills.post('/developer/upload-resource-files',summary='开发者中心-上传并保存技能挂载资源原文件及用途')
async def upload(files:list[UploadFile]=File(...),categories:str=Form(...),current_user=DependAuth):
    try:
        return SuccessResponse(data=await sources.upload(files,categories_value(categories),current_user))
    finally:
        for file in files:
            await file.close()

@developer_skills.post('/developer/upload-resource-version',summary='开发者中心-旧资源版本上传（已停用，请使用资源上传）',deprecated=True)
async def upload_version(source_id:int=Form(...),files:list[UploadFile]=File(...),categories:str=Form(...),current_user=DependAuth):
    try:
        raise DeveloperError('文件不再维护版本，请使用资源上传接口保存独立文件', 410)
    finally:
        for file in files:
            await file.close()

@developer_skills.get('/developer/download-resource-file',summary='开发者中心-按文件编号下载本人挂载资源原文件')
async def download(file_id:int=Query(...,ge=1,description='文件编号'),current_user=DependAuth):
    path,name=await sources.download(file_id,current_user)
    return FileResponse(path,filename=name)

@developer_skills.post('/developer/save-skill',summary='开发者中心-保存技能修改并校验修订号冲突')
async def save(data:DeveloperSkillSaveRequest,current_user=DependAuth):
    return SuccessResponse(data=await crud.output(await crud.save(data.skill_id,current_user,business_payload(data,DeveloperSkillForm)),current_user))

@developer_skills.post('/developer/delete-skill-draft',summary='开发者中心-软删除技能草稿并释放名称')
async def delete(data:SkillIdRequest,current_user=DependAuth):
    await crud.delete_draft(data.skill_id,current_user)
    return SuccessResponse(message='草稿已删除')

@developer_skills.post('/developer/offline-skill',summary='开发者中心-填写下线原因并下线技能')
async def offline(data:OfflineSkillBody,current_user=DependAuth):
    return SuccessResponse(data=await crud.output(await crud.offline(data.skill_id,current_user,business_payload(data,OfflineSkillRequest)),current_user))

@developer_skills.post('/developer/publish-skill',summary='开发者中心-核验当前版本调试成功后上线技能')
async def publish(data:SkillIdRequest,current_user=DependAuth):
    return SuccessResponse(data=await crud.output(await crud.publish(data.skill_id,current_user),current_user))

@developer_skills.post('/developer/register-debug-run',summary='开发者中心-登记沙箱调试任务并关联固定技能版本')
async def debug(data:RegisterDebugRunRequest,current_user=DependAuth):
    return SuccessResponse(data=await crud.output(await crud.record_debug_result(data.skill_id,current_user,business_payload(data,DeveloperDebugResult)),current_user))

@developer_skills.get('/developer/get-debug-run',summary='开发者中心-查询调试任务与技能版本关联')
async def debug_link(skill_id: int = Query(..., ge=1, le=2147483647),run_id:str=Query(...,min_length=1,max_length=128),current_user=DependAuth):
    return SuccessResponse(data=await crud.debug_link(skill_id,run_id,current_user))
