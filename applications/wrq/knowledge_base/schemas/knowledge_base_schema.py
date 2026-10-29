# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enums.chat_session_enum import DocumentStatus


class KnowledgeBaseBase(BaseModel):
    knowledge_name: Optional[str] = Field(default=None, max_length=128, description="知识库名称")
    description: Optional[str] = Field(default=None, max_length=500, description="知识库描述")
    is_public: Optional[bool] = Field(default=None, description="是否公开")
    chunk_size: Optional[int] = Field(default=None, ge=200, le=2000, description="分块大小(字符数)")
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=1000, description="分块重叠(字符数)")


class KnowledgeBaseCreate(KnowledgeBaseBase):
    knowledge_name: str = Field(..., min_length=1, max_length=128, description="知识库名称")
    description: Optional[str] = Field(default=None, max_length=500, description="知识库描述")
    is_public: bool = Field(default=False, description="是否公开")
    chunk_size: Optional[int] = Field(default=None, ge=200, le=2000, description="分块大小(字符数)")
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=1000, description="分块重叠(字符数)")

    @model_validator(mode="after")
    def validate_chunk_params(self):
        if (
                self.chunk_overlap is not None
                and self.chunk_size is not None
                and self.chunk_overlap > self.chunk_size // 2
        ):
            raise ValueError("分块重叠不能超过分块大小的一半")
        return self

    def create_dict(self):
        return self.model_dump(exclude_unset=True)


class KnowledgeBaseOut(BaseModel):
    id: str = Field(..., description="知识库ID")
    knowledge_name: str = Field(..., description="知识库名称")
    description: Optional[str] = Field(default=None, description="知识库描述")
    user_id: int = Field(..., description="所属用户ID")
    is_public: bool = Field(..., description="是否公开")
    chunk_size: Optional[int] = Field(default=None, description="分块大小(字符数)")
    chunk_overlap: Optional[int] = Field(default=None, description="分块重叠(字符数)")
    default_embedding_model: str = Field(..., description="默认向量化模型")
    created_time: datetime = Field(..., description="创建时间")
    updated_time: datetime = Field(..., description="更新时间")
    document_count: int = Field(default=0, description="文档数量")

    model_config = ConfigDict(from_attributes=True)


class DocumentCreate(BaseModel):
    """文档创建（CRUD 层）"""
    knowledge_base_id: str = Field(..., description="所属知识库ID")
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_path: str = Field(..., description="文件路径")
    file_size: int = Field(..., description="文件大小(字节)")
    content_hash: str = Field(..., description="文件内容SHA256")
    embedding_model: Optional[str] = Field(default=None, description="向量化模型")
    status: DocumentStatus = Field(
        default=DocumentStatus.PROCESSING, description="处理状态"
    )


class DocumentUpdate(BaseModel):
    """文档更新（CRUD 层）"""
    status: Optional[DocumentStatus] = Field(default=None, description="处理状态")
    chunk_count: Optional[int] = Field(default=None, description="分块数量")
    error_message: Optional[str] = Field(default=None, description="错误信息")


class DocumentChunkCreate(BaseModel):
    """文档分块创建（CRUD 层）"""
    document_id: str = Field(..., description="所属文档ID")
    content: str = Field(..., description="分块内容")
    chunk_index: int = Field(..., description="分块序号")
    page_number: Optional[int] = Field(default=None, description="PDF页码(从1开始)")


class DocumentOut(BaseModel):
    id: str = Field(..., description="文档ID")
    knowledge_base_id: str = Field(..., description="所属知识库ID")
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小(字节)")
    content_hash: Optional[str] = Field(default=None, description="文件内容SHA256")
    embedding_model: Optional[str] = Field(default=None, description="向量化模型")
    chunk_count: int = Field(..., description="分块数量")
    status: str = Field(..., description="处理状态")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    created_time: datetime = Field(..., description="创建时间")
    updated_time: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True)


class DocumentChunkOut(BaseModel):
    id: str = Field(..., description="分块ID")
    document_id: str = Field(..., description="所属文档ID")
    content: str = Field(..., description="分块内容")
    chunk_index: int = Field(..., description="分块序号")
    page_number: Optional[int] = Field(default=None, description="PDF页码(从1开始)")
    created_time: datetime = Field(..., description="创建时间")
    updated_time: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True)


class DocumentChunkUpdate(BaseModel):
    content: str = Field(..., min_length=1, description="分块内容")
