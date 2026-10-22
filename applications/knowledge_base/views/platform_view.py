"""定稿个人知识库 API。处理任务在响应后执行，状态保存在数据库。"""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.responses import FileResponse

from applications.base.platform_catalog import applications
from applications.base.validation_errors import ValidationResponseRoute, validation_issues
from applications.knowledge_base.models.knowledge_base_model import DocumentChunk
from applications.knowledge_base.schemas.platform_schema import DocumentEdit, KnowledgeForm, KnowledgeMount
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
            form = KnowledgeForm.model_validate_json(source)
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
    return SuccessResponse(data=[{"id": value, "name": value} for value in applications()])


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


@knowledge.get("/", summary="可见知识库列表：公开及本人私有；按名称搜索")
async def list_knowledge(search: str = "", offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                         current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    try:
        items, total = await service.list(current_user, search, offset=offset, limit=limit)
        return SuccessResponse(data=items, total=total)
    except Exception:
        LOGGER.exception("知识库查询失败")
        result = FailureResponse(message="知识库查询失败")
        result.status_code = 500
        return result


@knowledge.post("/", summary="创建知识库（source JSON 与至少一个 files）")
@knowledge.post("/form", summary="创建知识库表单")
async def create_knowledge(request: Request, background: BackgroundTasks, source: str = Form(...),
                           files: list[UploadFile] = File(default=[]), current_user: User = DependAuth,
                           service=Depends(get_knowledge_service)):
    return await save_form(request, background, source, files, current_user, service)


@knowledge.put("/{kb_id}", summary="保存知识库修改；版本递增；仅重处理变更文档")
async def update_knowledge(kb_id: str, request: Request, background: BackgroundTasks, source: str = Form(...),
                           files: list[UploadFile] = File(default=[]), current_user: User = DependAuth,
                           service=Depends(get_knowledge_service)):
    return await save_form(request, background, source, files, current_user, service, kb_id)


@knowledge.get("/{kb_id}", summary="知识库详情、文件状态及版本历史")
async def detail(kb_id: str, current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    return await respond(service.detail(kb_id, current_user))


@knowledge.get("/{kb_id}/documents", summary="知识库文件列表")
async def list_documents(kb_id: str, current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        return (await service.detail(kb_id, current_user))["documents"]
    return await respond(operation())


@knowledge.get("/{kb_id}/history", summary="知识库编辑历史")
async def history(kb_id: str, current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        return (await service.detail(kb_id, current_user))["history"]
    return await respond(operation())


@knowledge.get("/{kb_id}/documents/{doc_id}/preview", summary="文件解析后的 Markdown 预览（只返回文本）")
async def preview(kb_id: str, doc_id: str, current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        doc = await service.require_document(kb_id, doc_id, current_user)
        return {**service.document_out(doc), "markdown": doc.markdown or ""}
    return await respond(operation())


@knowledge.get("/{kb_id}/documents/{doc_id}/download", summary="下载知识库原文件")
async def download(kb_id: str, doc_id: str, current_user: User = DependAuth, service=Depends(get_knowledge_service)):
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


@knowledge.put("/{kb_id}/documents/{doc_id}/content", summary="编辑文本/Markdown；重建该文档索引")
async def edit_content(kb_id: str, doc_id: str, data: DocumentEdit, background: BackgroundTasks,
                        current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        result, jobs = await service.edit_text(kb_id, doc_id, current_user, data)
        await schedule(background, service, jobs)
        return await service.detail(result["id"], current_user)
    return await respond(operation())


@knowledge.post("/{kb_id}/retry", summary="仅创建者重试失败/崩溃残留任务")
@knowledge.post("/{kb_id}/documents/{doc_id}/retry", summary="重试单个文档")
async def retry(kb_id: str, background: BackgroundTasks, doc_id: str | None = None,
                 current_user: User = DependAuth, service=Depends(get_knowledge_service)):
    async def operation():
        jobs = await service.retry(kb_id, current_user, doc_id)
        await schedule(background, service, jobs)
        return {"document_ids": jobs, "status": "processing"}
    return await respond(operation())


@knowledge.get("/{kb_id}/chunks", summary="查看文档分块；遵循知识库读取权限")
async def chunks(kb_id: str, document_id: str | None = None, offset: int = Query(0, ge=0),
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


@knowledge.post("/{kb_id}/mounts", summary="将可见知识库挂载到本人已生成的技能并重新打包")
async def mount(kb_id: str, data: KnowledgeMount, current_user: User = DependAuth,
                 service=Depends(get_knowledge_service)):
    from applications.agent.services.skill_package_service import SkillPackageService, SkillBuildNotFound
    from applications.agent.services.skill_package_builder import SkillPackageError
    async def operation():
        await service.require(kb_id, current_user)
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
                built = await engine.rebuild_saved(skill_id, current_user, knowledge_base_id=kb_id,
                                                   resource_usage=data.resource_usage)
                results.append({"skill_id": skill_id, "status": "succeeded", "build": built})
            except (SkillPackageError, SkillBuildNotFound):
                results.append({"skill_id": skill_id, "status": "failed", "message": "请先补齐技能表单并生成基础包，或检查资源引用"})
        return {"items": results}
    return await respond(operation())
