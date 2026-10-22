# -*- coding: utf-8 -*-
from dataclasses import dataclass

from applications.knowledge_base.services.knowledge_base_crud import (
    DocumentChunkCrud,
    DocumentCrud,
    KnowledgeBaseCrud,
)


@dataclass
class KnowledgeBaseServices:
    """知识库模块服务组合，用于需要多模型联动的业务场景。"""

    kb: KnowledgeBaseCrud
    document: DocumentCrud
    chunk: DocumentChunkCrud


async def get_knowledge_base_crud() -> KnowledgeBaseCrud:
    """获取知识库 CRUD 服务实例"""
    return KnowledgeBaseCrud()


async def get_document_crud() -> DocumentCrud:
    """获取文档 CRUD 服务实例"""
    return DocumentCrud()


async def get_document_chunk_crud() -> DocumentChunkCrud:
    """获取文档分块 CRUD 服务实例"""
    return DocumentChunkCrud()


async def get_knowledge_base_services() -> KnowledgeBaseServices:
    """获取知识库模块组合服务"""
    return KnowledgeBaseServices(
        kb=KnowledgeBaseCrud(),
        document=DocumentCrud(),
        chunk=DocumentChunkCrud(),
    )
