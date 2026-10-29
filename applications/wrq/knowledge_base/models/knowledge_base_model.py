# -*- coding: utf-8 -*-
from tortoise import fields

from applications.base.services.scaffold import (
    ScaffoldModel,
    StateModel,
    TimestampMixin,
    unique_identify,
)
from enums.chat_session_enum import DocumentStatus


class KnowledgeBase(ScaffoldModel, StateModel, TimestampMixin):
    """知识库模型"""
    id = fields.CharField(default=unique_identify, max_length=64, pk=True, description="知识库ID")
    knowledge_name = fields.CharField(max_length=128, description="知识库名称")
    name_key = fields.CharField(max_length=64, null=True, unique=True)
    tag = fields.CharField(max_length=32, default="custom")
    application = fields.CharField(max_length=128, default="*")
    revision = fields.IntField(default=0)
    history = fields.JSONField(default=list)
    description = fields.TextField(null=True, description="知识库描述")
    user = fields.ForeignKeyField(
        "models.User",
        related_name="knowledge_bases",
        on_delete=fields.CASCADE,
        description="所属用户",
    )
    is_public = fields.BooleanField(default=False, description="是否公开")
    chunk_size = fields.IntField(null=True, description="分块大小(字符数)，为空时使用全局配置")
    chunk_overlap = fields.IntField(null=True, description="分块重叠(字符数)，为空时使用全局配置")

    documents: fields.ReverseRelation["Document"]

    class Meta:
        table = "keenrobot_knowledge_bases"


class Document(ScaffoldModel, TimestampMixin):
    """文档模型"""
    id = fields.CharField(default=unique_identify, max_length=64, pk=True, description="文档ID")
    knowledge_base = fields.ForeignKeyField(
        "models.KnowledgeBase",
        related_name="documents",
        on_delete=fields.CASCADE,
        description="所属知识库",
    )
    filename = fields.CharField(max_length=255, description="文件名")
    file_type = fields.CharField(max_length=32, default="pdf", description="文件类型(pdf/txt/docx)")
    file_path = fields.CharField(max_length=512, description="文件路径")
    file_size = fields.BigIntField(description="文件大小(字节)")
    content_hash = fields.CharField(max_length=64, null=True, description="文件内容SHA256")
    embedding_model = fields.CharField(max_length=64, null=True, description="向量化模型")
    chunk_count = fields.IntField(default=0, description="分块数量")
    status = fields.CharEnumField(
        DocumentStatus, max_length=32, default=DocumentStatus.PROCESSING, description="处理状态"
    )
    error_message = fields.TextField(null=True, description="错误信息")
    markdown = fields.TextField(null=True)
    generation = fields.IntField(default=1)
    indexed_generation = fields.IntField(default=0)
    processing_started_time = fields.DatetimeField(null=True)
    cleanup_vector_ids = fields.JSONField(default=list)
    is_deleted = fields.BooleanField(default=False)
    task_id = fields.CharField(max_length=64, null=True)
    task_dispatched_at = fields.DatetimeField(null=True)
    next_retry_at = fields.DatetimeField(null=True)
    deletion_retry_count = fields.IntField(default=0)
    deletion_retryable = fields.BooleanField(default=True)
    deletion_error_type = fields.CharField(max_length=64, null=True)
    # 原文件替换／Docling 转换产物同样保留清理线索，不能只写日志后遗失路径。
    cleanup_file_paths = fields.JSONField(default=list)
    artifact_paths = fields.JSONField(default=list)

    document_chunks: fields.ReverseRelation["DocumentChunk"]

    class Meta:
        table = "keenrobot_documents"
        unique_together = (("knowledge_base_id", "content_hash"),)


class DocumentChunk(ScaffoldModel, TimestampMixin):
    """文档分块模型"""
    id = fields.CharField(default=unique_identify, max_length=64, pk=True, description="分块ID")
    document = fields.ForeignKeyField(
        "models.Document",
        related_name="document_chunks",
        on_delete=fields.CASCADE,
        description="所属文档",
    )
    content = fields.TextField(description="分块内容")
    chunk_index = fields.IntField(description="分块序号")
    page_number = fields.IntField(null=True, description="PDF页码(从1开始)")
    chroma_id = fields.CharField(max_length=128, null=True, description="Chroma向量ID")
    source_metadata = fields.JSONField(default=dict)

    class Meta:
        table = "keenrobot_document_chunks"
