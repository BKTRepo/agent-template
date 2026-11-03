"""dev-knowledge document ingestion contract, protected by platform authentication."""
from fastapi import APIRouter, File, UploadFile, Form
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
    return await RagDocument.filter(job_id=job_id,owner_id=user.id).exists()

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

@conversion_router.get('/convert/status/{job_id}',summary='查询解析、术语、分块、嵌入及入库进度')
async def status(job_id: str,current_user: User = DependAuth):
    if not await owned(job_id,current_user):
        return NotFoundResponse(message='任务不存在或无访问权限')
    data = await RagDocumentService().get_document(job_id)
    return SuccessResponse(data=data)

@conversion_router.post('/convert/retry',summary='失败任务重试，校验产物后决定复用阶段')
async def retry(data: RetryConvert,current_user: User = DependAuth):
    if not await owned(data.job_id,current_user):
        return NotFoundResponse(message='任务不存在或无访问权限')
    job = await RagDocument.get(job_id=data.job_id)
    if job.knowledge_document_id:
        return ParameterResponse(message='该任务属于知识库文档，请通过知识库文档重试接口操作')
    try:
        return SuccessResponse(data=await RagPipelineService(RagDocumentService()).retry_document(data.job_id))
    except (ParameterException,NotFoundException) as exc:
        return ParameterResponse(message=exc.message)

@conversion_router.get('/documents/{job_id}/markdown',summary='获取处理后的Markdown')
async def markdown(job_id: str,current_user: User = DependAuth):
    if not await owned(job_id,current_user):
        return NotFoundResponse(message='任务不存在或无访问权限')
    return SuccessResponse(data=await RagDocumentService().get_document_markdown(job_id))

@conversion_router.get('/documents/{job_id}/terminology',summary='获取术语提取产物')
async def terminology(job_id: str,current_user: User = DependAuth):
    if not await owned(job_id,current_user):
        return NotFoundResponse(message='任务不存在或无访问权限')
    return SuccessResponse(data=await RagDocumentService().get_document_terminology(job_id))

@conversion_router.get('/documents/{job_id}/chunks',summary='获取最终入库分块')
async def chunks(job_id: str,current_user: User = DependAuth):
    if not await owned(job_id,current_user):
        return NotFoundResponse(message='任务不存在或无访问权限')
    return SuccessResponse(data=await RagDocumentService().get_document_chunks(job_id))
