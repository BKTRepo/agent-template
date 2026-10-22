# -*- coding: utf-8 -*-
import traceback

from fastapi import APIRouter, Depends, File, UploadFile

from applications.knowledge_base.dependencies import get_knowledge_base_crud
from applications.knowledge_base.schemas.knowledge_base_schema import (
    KnowledgeBaseCreate,
    DocumentChunkUpdate,
)
from applications.knowledge_base.services.knowledge_base_crud import KnowledgeBaseCrud
from applications.user.models.user_model import User
from configure import LOGGER
from core.exceptions import (
    DataBaseStorageException,
    NoPermissionException,
    NotFoundException,
    ParameterException,
)
from core.responses import (
    SuccessResponse,
    FailureResponse,
    NotFoundResponse,
    ForbiddenResponse,
    ParameterResponse,
    DataBaseStorageResponse,
)
from services import DependAuth

knowledge = APIRouter()


@knowledge.post("/", summary="知识库-新增知识库")
async def create_knowledge_base(
        kb_data: KnowledgeBaseCreate,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        result = await kb_crud.create_kb(current_user, kb_data)
        return SuccessResponse(data=result.model_dump(by_alias=True))
    except Exception as e:
        LOGGER.error(f"创建知识库失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"创建失败: {e}")


@knowledge.get("/", summary="知识库-查询知识库列表")
async def list_knowledge_bases(
        search: str = None,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        items = await kb_crud.list_kbs(current_user, search)
        data = [item.model_dump(by_alias=True) for item in items]
        return SuccessResponse(data=data, total=len(data))
    except Exception as e:
        LOGGER.error(f"查询知识库列表失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@knowledge.get("/{kb_id}", summary="知识库-按id查询知识库详情")
async def get_knowledge_base(
        kb_id: str,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        result = await kb_crud.get_kb(kb_id, current_user)
        return SuccessResponse(data=result.model_dump(by_alias=True))
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询知识库详情失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@knowledge.put("/{kb_id}", summary="知识库-按id更新知识库")
async def update_knowledge_base(
        kb_id: str,
        kb_data: KnowledgeBaseCreate,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        result = await kb_crud.update_kb(kb_id, current_user, kb_data)
        return SuccessResponse(data=result.model_dump(by_alias=True))
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"更新知识库失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"更新失败: {e}")


@knowledge.delete("/{kb_id}", summary="知识库-按id删除知识库")
async def delete_knowledge_base(
        kb_id: str,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        await kb_crud.delete_kb(kb_id, current_user)
        return SuccessResponse(message="知识库已删除")
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"删除知识库失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"删除失败: {e}")


@knowledge.post("/{kb_id}/documents", summary="知识库-上传文档")
async def upload_document(
        kb_id: str,
        file: UploadFile = File(...),
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        doc = await kb_crud.upload_document(kb_id, current_user, file)
        return SuccessResponse(data=doc.model_dump())
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except ParameterException as e:
        return ParameterResponse(message=e.message)
    except DataBaseStorageException as e:
        return DataBaseStorageResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"上传文档失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"上传失败: {e}")


@knowledge.get("/{kb_id}/documents", summary="知识库-查询文档列表")
async def list_documents(
        kb_id: str,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        docs = await kb_crud.list_documents(kb_id, current_user)
        data = [doc.model_dump() for doc in docs]
        return SuccessResponse(data=data, total=len(data))
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询文档列表失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@knowledge.post("/{kb_id}/documents/{doc_id}/retry", summary="知识库-重试处理失败文档")
async def retry_document(
        kb_id: str,
        doc_id: str,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        doc = await kb_crud.retry_document(kb_id, doc_id, current_user)
        return SuccessResponse(data=doc.model_dump())
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except ParameterException as e:
        return ParameterResponse(message=e.message)
    except DataBaseStorageException as e:
        return DataBaseStorageResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"重试文档处理失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"重试失败: {e}")


@knowledge.delete("/{kb_id}/documents/{doc_id}", summary="知识库-按id删除文档")
async def delete_document(
        kb_id: str,
        doc_id: str,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        await kb_crud.delete_document(kb_id, doc_id, current_user)
        return SuccessResponse(message="文档已删除")
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"删除文档失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"删除失败: {e}")


@knowledge.get("/{kb_id}/chunks", summary="知识库-查询知识块列表")
async def list_chunks(
        kb_id: str,
        document_id: str = None,
        page: int = 1,
        page_size: int = 50,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        chunks = await kb_crud.list_chunks(
            kb_id, current_user, document_id, page, page_size
        )
        data = [chunk.model_dump() for chunk in chunks]
        return SuccessResponse(data=data, total=len(data))
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询知识块列表失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@knowledge.get("/{kb_id}/chunks/{chunk_id}", summary="知识库-按id查询知识块详情")
async def get_chunk(
        kb_id: str,
        chunk_id: str,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        chunk = await kb_crud.get_chunk(kb_id, chunk_id, current_user)
        return SuccessResponse(data=chunk.model_dump())
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询知识块详情失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@knowledge.put("/{kb_id}/chunks/{chunk_id}", summary="知识库-按id更新知识块")
async def update_chunk(
        kb_id: str,
        chunk_id: str,
        chunk_data: DocumentChunkUpdate,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        chunk = await kb_crud.update_chunk(
            kb_id, chunk_id, current_user, chunk_data
        )
        return SuccessResponse(data=chunk.model_dump())
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"更新知识块失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"更新失败: {e}")


@knowledge.delete("/{kb_id}/chunks/{chunk_id}", summary="知识库-按id删除知识块")
async def delete_chunk(
        kb_id: str,
        chunk_id: str,
        current_user: User = DependAuth,
        kb_crud: KnowledgeBaseCrud = Depends(get_knowledge_base_crud),
):
    try:
        await kb_crud.delete_chunk(kb_id, chunk_id, current_user)
        return SuccessResponse(message="知识块已删除")
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except NoPermissionException as e:
        return ForbiddenResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"删除知识块失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"删除失败: {e}")
