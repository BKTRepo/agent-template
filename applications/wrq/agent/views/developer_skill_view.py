import json
from fastapi import APIRouter, File, Form, Query, UploadFile
from starlette.responses import FileResponse
from applications.wrq.http import WrqRoute
from applications.wrq.agent.schemas.agent_schema import DeveloperDebugResult, DeveloperSkillForm, OfflineSkillRequest
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


@developer_skills.get('/developer/context',summary='WRQ-平台当前身份；不提供独立登录')
async def context(current_user=DependAuth):
    login = user_login_name(current_user)
    return SuccessResponse(data={'id':login,'login_name':login,'name':current_user.alias or current_user.username})

@developer_skills.get('/developer/metadata',summary='WRQ-技能大类、门户应用及用途字典')
async def metadata(current_user=DependAuth):
    result=SuccessResponse(data=await crud.metadata())
    result.headers['Cache-Control'] = 'no-store, max-age=0'
    result.headers['Pragma'] = 'no-cache'
    return result

@developer_skills.get('/developer',summary='WRQ-本人技能分页')
@developer_skills.get('/developer/',include_in_schema=False)
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

@developer_skills.post('/developer',summary='WRQ-创建草稿')
@developer_skills.post('/developer/',include_in_schema=False)
async def create(data:DeveloperSkillForm,current_user=DependAuth):
    return SuccessResponse(data=await crud.output(await crud.create(current_user,data),current_user))

@developer_skills.post('/developer/resources',summary='WRQ-保存挂载文件原件及用途')
async def upload(files:list[UploadFile]=File(...),categories:str=Form(...),current_user=DependAuth):
    try:
        return SuccessResponse(data=await sources.upload(files,categories_value(categories),current_user))
    finally:
        for file in files:
            await file.close()

@developer_skills.post('/developer/resources/{source_id}/versions',summary='WRQ-保存文件新版本')
async def upload_version(source_id:int,files:list[UploadFile]=File(...),categories:str=Form(...),current_user=DependAuth):
    try:
        raise DeveloperError('文件不再维护版本，请使用资源上传接口保存独立文件', 410)
    finally:
        for file in files:
            await file.close()

@developer_skills.get('/developer/resources/{file_id}/download',summary='WRQ-按文件编号下载本人挂载原文件')
async def download(file_id:int,current_user=DependAuth):
    path,name=await sources.download(file_id,current_user)
    return FileResponse(path,filename=name)

@developer_skills.put('/developer/{skill_id}',summary='WRQ-保存修改并生成新版本')
async def save(skill_id:str,data:DeveloperSkillForm,current_user=DependAuth):
    return SuccessResponse(data=await crud.output(await crud.save(skill_id,current_user,data),current_user))

@developer_skills.delete('/developer/{skill_id}',summary='WRQ-软删除草稿；释放名称')
async def delete(skill_id:str,current_user=DependAuth):
    await crud.delete_draft(skill_id,current_user)
    return SuccessResponse(message='草稿已删除')

@developer_skills.post('/developer/{skill_id}/offline',summary='WRQ-填写原因并下线')
async def offline(skill_id:str,data:OfflineSkillRequest,current_user=DependAuth):
    return SuccessResponse(data=await crud.output(await crud.offline(skill_id,current_user,data),current_user))

@developer_skills.post('/developer/{skill_id}/publish',summary='WRQ-核对沙箱当前版本成功结果后上线')
async def publish(skill_id:str,current_user=DependAuth):
    return SuccessResponse(data=await crud.output(await crud.publish(skill_id,current_user),current_user))

@developer_skills.post('/developer/{skill_id}/debug-result',summary='WRQ-关联同事沙箱run_id，不接受前端伪造成功')
@developer_skills.post('/developer/{skill_id}/debug-runs',summary='WRQ-任务创建后立即登记固定技能版本，支持queued/running')
async def debug(skill_id:str,data:DeveloperDebugResult,current_user=DependAuth):
    return SuccessResponse(data=await crud.output(await crud.record_debug_result(skill_id,current_user,data),current_user))

@developer_skills.get('/developer/{skill_id}/debug-runs/{run_id}',summary='WRQ-核对找回任务属于哪个技能版本')
async def debug_link(skill_id:str,run_id:str,current_user=DependAuth):
    return SuccessResponse(data=await crud.debug_link(skill_id,run_id,current_user))
