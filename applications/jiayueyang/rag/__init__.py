# -*- coding: utf-8 -*-
"""RAG 基础能力组件（项目级共享）。

提供模型调用（LLM / Embedding / Rerank / VLM）、文档分块、向量存储、
检索问答编排、查询改写、术语抽取、多模态分析、侧车文件等通用 RAG 基础设施,
供各业务应用复用。组件实现多移植自 LightRAG 并按本项目风格改造。

组件一览:
- llm / embedding / rerank / vlm: OpenAI 兼容模型客户端
- chunker: 文档分块（R 递归字符）
- milvus_store: Milvus Server C/S 向量存储与内置 BM25
- query: 检索问答引擎（naive / hybrid / bypass）
- bm25 / query_rewriter / terminology: 稀疏检索、查询改写与术语库
- multimodal / sidecar: 多模态分析与 LightRAG 兼容侧车文件
"""
from applications.jiayueyang.rag.bm25 import BM25Searcher
from applications.jiayueyang.rag.chunker import chunk_document
from applications.jiayueyang.rag.embedding import embed_chunks, embed_texts, save_embeddings
from applications.jiayueyang.rag.llm import chat_completion
from applications.jiayueyang.rag.query import QueryParam, QueryResult, run_query
from applications.jiayueyang.rag.rerank import rerank_chunks

__all__ = (
    "BM25Searcher",
    "chunk_document",
    "embed_chunks",
    "embed_texts",
    "save_embeddings",
    "chat_completion",
    "QueryParam",
    "QueryResult",
    "run_query",
    "rerank_chunks",
)
