# -*- coding: utf-8 -*-
from fastapi import APIRouter

from .rag_view import rag_health, rag_business
from .chat_view import chat_business
from .term_mapping_view import term_mapping_router

# 公开路由: 健康检查类接口, 无需鉴权
rag_public_router = APIRouter()
# 业务路由: 文档解析/流水线管控/RAG 问答/对话历史等, 按模板约定由挂载处统一施加 DependAuth
rag_secure_router = APIRouter()

rag_public_router.include_router(rag_health)
rag_secure_router.include_router(rag_business)
rag_secure_router.include_router(chat_business)
rag_secure_router.include_router(term_mapping_router)

__all__ = (
    "rag_public_router",
    "rag_secure_router",
)
