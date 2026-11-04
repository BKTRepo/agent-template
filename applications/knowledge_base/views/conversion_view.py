"""dev-knowledge document ingestion contract, protected by platform authentication."""
from fastapi import APIRouter, File, UploadFile, Form, Query
from pydantic import BaseModel, Field
from applications.knowledge_base.services.rag_pipeline import RagPipelineService
from applications.knowledge_base.services.rag_service import RagDocumentService
from applications.knowledge_base.models.rag_document_model import RagDocument
from applications.knowledge_base.processing.file_utils import read_upload_with_cap
from applications.user.models.user_model import User
from configure import LOGGER, PROJECT_CONFIG
from core.responses import SuccessResponse, FailureResponse, NotFoundResponse, ParameterResponse
from core.exceptions import ParameterException, DataAlreadyExistsException, NotFoundException
from services import DependAuth

conversion_router = APIRouter()

class RetryConvert(BaseModel):
    job_id: str = Field(min_length=1,max_length=64)

async def owned(job_id, user):
    job = await RagDocument.get_or_none(job_id=job_id)
    if not job:
        return False
    if job.owner_id == user.id:
        return True
    if job.knowledge_document_id:
        from applications.knowledge_base.models.knowledge_base_model import Document
        from applications.knowledge_base.services.platform_service import KnowledgeService, KnowledgeError
        document = await Document.get_or_none(id=job.knowledge_document_id, is_deleted=False)
        if document:
            try:
                await KnowledgeService().require(document.knowledge_base_id, user)
                return True
            except KnowledgeError:
                pass
    return False

@conversion_router.post('/convert', summary='上传文件并执行完整知识处理流水线')
async def convert(file: UploadFile = File(...), do_ocr: bool = Form(False), force_ocr: bool = Form(False),
                  enable_vlm: bool = Form(False), current_user: User = DependAuth):
    try:
        raw = await read_upload_with_cap(file, PROJECT_CONFIG.RAG_MAX_UPLOAD_MB * 1024 * 1024)
        service = RagDocumentService()
        data = await RagPipelineService(service).submit_conversion(file_bytes=raw,filename=file.filename or '',
            content_type=file.content_type,owner_id=current_user.id,do_ocr=False,force_ocr=False,enable_vlm=False)
        await RagDocument.filter(job_id=data['job_id']).update(owner_id=current_user.id)
        return SuccessResponse(data=data)
    except (ParameterException,DataAlreadyExistsException) as exc:
        return ParameterResponse(message=exc.message)
    except Exception:
        LOGGER.exception('知识处理任务提交失败')
        return FailureResponse(message='任务提交失败，请查看服务端日志')
    finally:
        await file.close()

@conversion_router.get('/convert/status',summary='知识处理-查询解析、术语、分块、嵌入及入库进度')
async def status(job_id: str=Query(...,min_length=1,max_length=64),current_user: User = DependAuth):
    if not await owned(job_id,current_user):
        return NotFoundResponse(message='任务不存在或无访问权限')
    from applications.knowledge_base.services.conversion_links import sync_conversion
    await sync_conversion(await RagDocument.get(job_id=job_id))
    data = await RagDocumentService().get_document(job_id)
    return SuccessResponse(data=data)

@conversion_router.post('/convert/retry',summary='失败任务重试，校验产物后决定复用阶段')
async def retry(data: RetryConvert,current_user: User = DependAuth):
    if not await owned(data.job_id,current_user):
        return NotFoundResponse(message='任务不存在或无访问权限')
    job = await RagDocument.get(job_id=data.job_id)
    if job.knowledge_document_id:
        from applications.knowledge_base.models.knowledge_base_model import Document
        from applications.knowledge_base.services.platform_service import KnowledgeService, KnowledgeError
        document = await Document.get_or_none(id=job.knowledge_document_id, is_deleted=False)
        if not document:
            return NotFoundResponse(message='知识库文档不存在或无重试权限')
        try:
            await KnowledgeService().require(document.knowledge_base_id, current_user, write=True)
        except KnowledgeError:
            return NotFoundResponse(message='知识库文档不存在或无重试权限')
    try:
        result = await RagPipelineService(RagDocumentService()).retry_document(data.job_id)
        from applications.knowledge_base.services.conversion_links import sync_conversion
        await sync_conversion(await RagDocument.get(job_id=data.job_id))
        return SuccessResponse(data=result)
    except (ParameterException,NotFoundException) as exc:
        return ParameterResponse(message=exc.message)

@conversion_router.get('/documents/markdown',summary='知识处理-查询处理后的Markdown')
async def markdown(job_id: str=Query(...,min_length=1,max_length=64),current_user: User = DependAuth):
    if not await owned(job_id,current_user):
        return NotFoundResponse(message='任务不存在或无访问权限')
    return SuccessResponse(data=await RagDocumentService().get_document_markdown(job_id))

@conversion_router.get('/documents/terminology',summary='知识处理-查询术语提取产物')
async def terminology(job_id: str=Query(...,min_length=1,max_length=64),current_user: User = DependAuth):
    if not await owned(job_id,current_user):
        return NotFoundResponse(message='任务不存在或无访问权限')
    return SuccessResponse(data=await RagDocumentService().get_document_terminology(job_id))

@conversion_router.get('/documents/chunks',summary='知识处理-查询最终入库分块')
async def chunks(job_id: str=Query(...,min_length=1,max_length=64),current_user: User = DependAuth):
    if not await owned(job_id,current_user):
        return NotFoundResponse(message='任务不存在或无访问权限')
    return SuccessResponse(data=await RagDocumentService().get_document_chunks(job_id))
