import json
from pydantic import BaseModel, ConfigDict, Field, model_validator
from fastapi import APIRouter, File, Form, Query, UploadFile
from starlette.responses import FileResponse
from applications.wrq.http import WrqRoute
from applications.wrq.agent.schemas.agent_schema import DeveloperDebugResult, DeveloperSkillForm, OfflineSkillRequest, SkillPolishFields
from applications.wrq.agent.schemas.api_request_schema import (
    DeveloperSkillSaveRequest, OfflineSkillBody, RegisterDebugRunRequest,
    SkillIdRequest, business_payload,
)
from applications.wrq.agent.services.developer_skill_crud import DeveloperSkillCrud, DeveloperError
from applications.wrq.agent.services.source_service import SourceService
from applications.wrq.agent.services.skill_polish import polish_skill_form
from core.responses import SuccessResponse
from applications.wrq.auth import DependAuth, user_login_name
from applications.wrq.agent.models.agent_model import SkillDisplayStatus

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

@developer_skills.get('/developer/get-skill',summary='开发者中心-按编号查询本人技能及当前知识库引用')
async def get_skill(skill_id: int = Query(..., ge=1, le=2147483647), current_user=DependAuth):
    result = SuccessResponse(data=await crud.output(await crud.get(skill_id, current_user), current_user))
    result.headers['Cache-Control'] = 'no-store, max-age=0'
    return result


@developer_skills.get('/developer/list-skills',summary='开发者中心-按实现名称、技能类、状态和所属应用分页筛选本人技能')
async def list_skills(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                     name: str = Query('', max_length=128), class_id: int | None = Query(None, ge=1, le=2147483647),
                     status: SkillDisplayStatus | None = Query(None), application: str = Query('', max_length=128), current_user=DependAuth):
    # 列表用于开发者中心的刷新与分页，禁止浏览器/代理复用旧快照。
    filters=dict(name=name,class_id=class_id,status=status,application=application)
    rows,total=await crud.list(current_user,page=page,page_size=page_size,**filters)
    pages=max(1,(total+page_size-1)//page_size)
    # 删除最后一页记录后，刷新可能仍带着旧页码；回退到最后有效页，避免前端停在空白页。
    if page > pages:
        page=pages
        rows,total=await crud.list(current_user,page=page,page_size=page_size,**filters)
    from applications.wrq.agent.services.knowledge_notification_service import counts
    update_counts = await counts(current_user, [r.id for r in rows])
    result=SuccessResponse(data={'items':[
        await crud.output(r,current_user,knowledge_update_count=update_counts.get(r.id,0),include_markdown=False)
        for r in rows
    ], 'total':total,
        'page':page, 'page_size':page_size, 'pages':pages})
    result.headers['Cache-Control'] = 'no-store, max-age=0'
    result.headers['Pragma'] = 'no-cache'
    return result


class KnowledgeUpdateSeen(BaseModel):
    model_config = ConfigDict(extra='forbid')
    notification_id: int = Field(gt=0, le=2147483647, strict=True)
    seen_revision: int = Field(ge=0, le=2147483647, strict=True)


class KnowledgeUpdatesRead(BaseModel):
    model_config = ConfigDict(extra='forbid')
    skill_id: int = Field(gt=0, le=2147483647, strict=True)
    items: list[KnowledgeUpdateSeen] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_items(self):
        if len({item.notification_id for item in self.items}) != len(self.items):
            raise ValueError('提醒编号不能重复')
        return self


@developer_skills.get('/developer/get-knowledge-update-summary', summary='开发者中心-查询全部本人技能知识库未读提醒汇总')
async def knowledge_update_summary(current_user=DependAuth):
    from applications.wrq.agent.services.knowledge_notification_service import summary
    response = SuccessResponse(data=await summary(current_user))
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response


@developer_skills.get('/developer/get-knowledge-updates', summary='开发者中心-查询本人技能挂载知识库的未读更新')
async def knowledge_updates(skill_id: int = Query(..., ge=1, le=2147483647), current_user=DependAuth):
    from applications.wrq.agent.services.knowledge_notification_service import details
    response = SuccessResponse(data=await details(skill_id, current_user))
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response


@developer_skills.post('/developer/mark-knowledge-updates-read', summary='开发者中心-按实际看到的知识库版本确认提醒已读')
async def mark_knowledge_updates_read(data: KnowledgeUpdatesRead, current_user=DependAuth):
    from applications.wrq.agent.services.knowledge_notification_service import mark_read
    response = SuccessResponse(data=await mark_read(data.skill_id, data.items, current_user))
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response

@developer_skills.post('/developer/polish-form', summary='开发者中心-AI润色新建技能表单')
async def polish_form(data: SkillPolishFields, current_user=DependAuth):
    response = SuccessResponse(data=await polish_skill_form(data))
    response.headers['Cache-Control'] = 'no-store'
    return response


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
