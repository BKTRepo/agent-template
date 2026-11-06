"""定稿个人知识库 API。处理任务在响应后执行，状态保存在数据库。"""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.responses import FileResponse
from applications.wrq.platform_catalog import application_catalog as load_applications

from applications.wrq.validation_errors import ValidationResponseRoute, validation_issues
from applications.knowledge_base.models.knowledge_base_model import DocumentChunk
from applications.knowledge_base.schemas.platform_schema import KnowledgeContentEdit, KnowledgeForm, KnowledgeCreateForm, KnowledgeMountRequest, KnowledgeRetry
from applications.knowledge_base.services.platform_service import KnowledgeError, KnowledgeService, get_knowledge_service
from applications.user.models.user_model import User
from configure import LOGGER, PROJECT_CONFIG
from core.responses import SuccessResponse, ParameterResponse, NotFoundResponse, ForbiddenResponse, FailureResponse
from services import DependAuth

knowledge = APIRouter(route_class=ValidationResponseRoute)


async def respond(operation):
    try:
        return SuccessResponse(data=await operation)
    except KnowledgeError as exc:
        cls = {404: NotFoundResponse, 403: ForbiddenResponse}.get(exc.status_code, ParameterResponse)
        response = cls(message=str(exc), data={"errors": [{"field": exc.field, "reason": str(exc)}]})
        response.status_code = exc.status_code
        return response
    except Exception:
        LOGGER.exception("知识库接口异常")
        response = FailureResponse(message="知识库服务异常，请联系管理员查看服务器日志")
        response.status_code = 500
        return response


async def schedule(background, service, jobs):
    if PROJECT_CONFIG.KNOWLEDGE_TASK_MODE == "inline":
        for doc_id in jobs:
            background.add_task(service.process, doc_id)
    else:
        from applications.knowledge_base.services.document_jobs import dispatch_jobs
        # SQL 已提交；提交失败由持久文档任务回显，不能落回 Web 线程假装执行成功。
        await dispatch_jobs(jobs)


async def save_form(request, background, source, files, user, service, kb_id=None):
    multipart = await request.form()
    uploads = [(key, value) for key, value in multipart.multi_items() if isinstance(value, StarletteUploadFile)]
    try:
        if any(key != "files" for key, _ in uploads):
            raise KnowledgeError("文件请统一通过 files 字段上传", "files")
        try:
            form_type = KnowledgeCreateForm if kb_id is None else KnowledgeForm
            form = form_type.model_validate_json(source)
        except ValidationError as exc:
            result = ParameterResponse(message="source 不符合知识库表单合同",
                data={"errors": validation_issues(exc.errors(), knowledge=True)})
            result.status_code = 400
            return result
        async def operation():
            result, jobs = await service.save(user, form, files, kb_id=kb_id)
            await schedule(background, service, jobs)
            return await service.detail(result["id"], user)
        return await respond(operation())
    except KnowledgeError as exc:
        async def failed():
            raise exc
        return await respond(failed())
    finally:
        for _, upload in uploads:
            await upload.close()


@knowledge.get("/applications", summary="知识库和开发者中心-应用选择目录")
async def application_catalog(current_user: User = DependAuth):
    return SuccessResponse(data=await load_applications())


@knowledge.get('/get-form-metadata', summary='知识库-查询应用目录和已启用标签配置')
async def form_metadata(current_user: User = DependAuth):
    from applications.knowledge_base.services.tag_catalog import tag_options
    return SuccessResponse(data={'applications': await load_applications(), 'tags': await tag_options()})


class TagSave(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: int | None = Field(default=None, ge=1)
    code: str = Field(min_length=1, max_length=32, pattern=r'^[a-z][a-z0-9_-]*$')
    name: str = Field(min_length=1, max_length=64)
    is_enabled: bool = True
    sort_order: int = Field(default=0, ge=0)


@knowledge.get('/tags', summary='知识库标签-查询配置，管理员可包含已停用项')
async def list_tags(include_disabled: bool = False, current_user: User = DependAuth):
    from applications.knowledge_base.services.tag_catalog import tag_options
    if include_disabled and not current_user.is_superuser:
        result = ForbiddenResponse(message='仅管理员可管理标签配置'); result.status_code = 403
        return result
    return SuccessResponse(data=await tag_options(include_disabled))


@knowledge.post('/tags/save', summary='知识库标签-管理员新增或修改名称、排序及启用状态')
async def save_tag(data: TagSave, current_user: User = DependAuth):
    from applications.knowledge_base.models.knowledge_base_model import KnowledgeTag
    from tortoise.exceptions import IntegrityError
    if not current_user.is_superuser:
        result = ForbiddenResponse(message='仅管理员可管理标签配置'); result.status_code = 403
        return result
    async def operation():
        row = await KnowledgeTag.get_or_none(id=data.id) if data.id else KnowledgeTag(code=data.code)
        if row is None:
            raise KnowledgeError('标签不存在', 'id', 404)
        if row.code != data.code:
            raise KnowledgeError('标签代码创建后不可修改，请修改显示名称或新增标签', 'code')
        row.name, row.is_enabled, row.sort_order = data.name, data.is_enabled, data.sort_order
        try:
            await row.save()
        except IntegrityError as exc:
            raise KnowledgeError('标签代码已存在', 'code') from exc
        return {'id': row.id, 'code': row.code, 'name': row.name, 'is_enabled': row.is_enabled, 'sort_order': row.sort_order}
    return await respond(operation())


@knowledge.get("/name-availability", summary="知识库名称唯一性预校验")
async def name_availability(name: str = Query(min_length=1, max_length=128), exclude_id: str | None = None,
                            current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        if not name.strip():
            raise KnowledgeError("请填写知识库名称", "knowledge_name")
        if exclude_id:
            await service.require(exclude_id, current_user, write=True)
        try:
            await service.check_name(name, exclude_id)
            return {"available": True}
        except KnowledgeError:
            return {"available": False}
    return await respond(operation())


@knowledge.get("/list", summary="知识库-查询公开及本人知识库列表")
async def list_knowledge(search: str = "", offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=10),
                         current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    try:
        items, total = await service.list(current_user, search, offset=offset, limit=limit)
        return SuccessResponse(data=items, total=total)
    except Exception:
        LOGGER.exception("知识库查询失败")
        result = FailureResponse(message="知识库查询失败")
        result.status_code = 500
        return result


@knowledge.post("/create", summary="知识库-创建知识库并关联上传文档转换任务")
async def create_knowledge(request: Request, background: BackgroundTasks, source: str = Form(...),
                           files: list[UploadFile] = File(default=[]), current_user: User = DependAuth,
                           service=Depends(get_knowledge_service)):
    return await save_form(request, background, source, files, current_user, service)


@knowledge.post("/save", summary="知识库-保存修改并递增版本")
async def update_knowledge(request: Request, background: BackgroundTasks, kb_id: int = Form(..., ge=1), source: str = Form(...),
                           files: list[UploadFile] = File(default=[]), current_user: User = DependAuth,
                           service=Depends(get_knowledge_service)):
    return await save_form(request, background, source, files, current_user, service, kb_id)


@knowledge.get("/detail", summary="知识库-查询详情、文件状态及版本历史")
async def detail(kb_id: int, current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    return await respond(service.detail(kb_id, current_user))


@knowledge.get("/documents", summary="知识库-查询文件列表")
async def list_documents(kb_id: int, current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        return (await service.detail(kb_id, current_user))["documents"]
    return await respond(operation())


@knowledge.get("/history", summary="知识库-查询编辑历史")
async def history(kb_id: int, current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        return (await service.detail(kb_id, current_user))["history"]
    return await respond(operation())


@knowledge.get("/documents/preview", summary="知识库-查询文件解析内容预览")
async def preview(kb_id: int, doc_id: int, current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        doc = await service.require_document(kb_id, doc_id, current_user)
        return {**service.document_out(doc), "markdown": doc.markdown or ""}
    return await respond(operation())


@knowledge.get("/documents/download", summary="知识库-下载原文件")
async def download(kb_id: int, doc_id: int, current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    try:
        doc = await service.require_document(kb_id, doc_id, current_user)
        path = Path(doc.file_path).resolve()
        if not path.is_relative_to(PROJECT_CONFIG.upload_path.resolve()) or not path.is_file():
            raise KnowledgeError("原文件不存在", status_code=404)
        return FileResponse(path, filename=doc.filename, media_type="application/octet-stream")
    except KnowledgeError as exc:
        async def failed():
            raise exc
        return await respond(failed())


@knowledge.post("/documents/save-content", summary="知识库-保存文本内容并重建索引")
async def edit_content(data: KnowledgeContentEdit, background: BackgroundTasks,
                        current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        result, jobs = await service.edit_text(data.kb_id, data.doc_id, current_user, data)
        await schedule(background, service, jobs)
        return await service.detail(result["id"], current_user)
    return await respond(operation())


@knowledge.post("/retry", summary="知识库-重试本人失败文档或残留任务")
async def retry(data: KnowledgeRetry, background: BackgroundTasks,
                 current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        jobs = await service.retry(data.kb_id, current_user, data.doc_id)
        await schedule(background, service, jobs)
        return {"document_ids": jobs, "status": "processing"}
    return await respond(operation())


@knowledge.get("/chunks", summary="知识库-查询文档分块")
async def chunks(kb_id: int, document_id: int | None = None, offset: int = Query(0, ge=0),
                  limit: int = Query(50, ge=1, le=100), current_user: User = DependAuth,
                  service=Depends(get_knowledge_service)):
    async def operation():
        await service.require(kb_id, current_user)
        qs = DocumentChunk.filter(document__knowledge_base_id=kb_id, document__is_deleted=False)
        if document_id:
            qs = qs.filter(document_id=document_id)
        rows = await qs.order_by("document_id", "chunk_index").offset(offset).limit(limit)
        return [{"id": row.id, "document_id": row.document_id, "content": row.content,
                 "chunk_index": row.chunk_index, "source_metadata": row.source_metadata} for row in rows]
    return await respond(operation())


@knowledge.post("/mounts", summary="知识库-旧版指定技能挂载并重新打包")
async def mount(data: KnowledgeMountRequest, current_user: User = DependAuth,
                 service=Depends(get_knowledge_service)):
    from applications.wrq.agent.services.skill_package_service import SkillPackageService, SkillBuildNotFound
    from applications.wrq.agent.services.skill_package_builder import SkillPackageError
    from applications.wrq.agent.services.developer_skill_crud import DeveloperError
    from applications.wrq.agent.models.agent_model import SkillVersion
    kb_id = data.kb_id
    async def operation():
        detail = await service.detail(kb_id, current_user)
        if detail['status'] != 'completed':
            raise KnowledgeError('知识库处理未完成，暂不可挂载到技能', 'knowledge_base_id', 409)
        engine = SkillPackageService()
        # 先验证整批身份归属，不允许混入他人的 Skill。
        for skill_id in dict.fromkeys(data.skill_ids):
            try:
                await engine.require_skill(skill_id, current_user)
            except SkillBuildNotFound as exc:
                raise KnowledgeError("目标技能不存在或非本人创建", "skill_ids", 403) from exc
        results = []
        for skill_id in dict.fromkeys(data.skill_ids):
            try:
                skill = await engine.require_skill(skill_id, current_user)
                version = await SkillVersion.get_or_none(id=skill.current_version_id)
                built = await engine.rebuild_saved(skill_id, current_user, knowledge_base_id=kb_id,
                                                   resource_usage=data.resource_usage,
                                                   expected_version=version.version if version else None)
                results.append({"skill_id": skill_id, "status": "succeeded", "build": built})
            except (SkillPackageError, SkillBuildNotFound, DeveloperError):
                results.append({"skill_id": skill_id, "status": "failed", "message": "请先补齐技能表单并生成基础包，或检查资源引用"})
        return {"items": results}
    return await respond(operation())
