# -*- coding: utf-8 -*-
"""
RAG 智能文档解析与问答应用 - jiayueyang 个人模块。

功能:
- PDF 文档上传与智能解析（基于 IBM Docling）
- 多策略文档分块（P/R/F/V）
- 向量嵌入与存储（Milvus Server C/S）
- RAG 问答（naive / hybrid / bypass 模式）
- SSE 流式响应

分层说明:
- 通用 RAG 基础能力（模型调用/分块/向量库/检索编排/查询改写/术语/多模态/侧车）
  位于本应用自有目录 rag/（应用自包含, 便于整目录迁移至 zsj 模板仓库,
  不与 zsj 既有的 applications/base/rag 旧版库冲突）
- 模型基类 scaffold 位于本应用 services/scaffold.py（与 zsj 的 base 版本同源）
- 通用文档工具（docling 客户端与结果解包、PDF 工具、Markdown 清洗）位于 common/
- 业务编排: models/ schemas/ services/ views/ + dependencies.py
"""
