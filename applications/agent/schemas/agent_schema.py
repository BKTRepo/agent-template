# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SkillBase(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128, description="技能名称")
    description: Optional[str] = Field(default=None, description="技能描述")
    is_enabled: Optional[bool] = Field(default=None, description="是否启用")
    config: Optional[dict[str, Any]] = Field(default=None, description="技能配置")

    @field_validator("config")
    @classmethod
    def protect_parser_state(cls, value):
        if value and {"parser_revision", "latest_build_id", "parser_source"}.intersection(value):
            raise ValueError("构建版本、构建 ID 和解析源由 Skill 生成接口维护，不能通过 config 覆盖")
        return value


class SkillCreate(SkillBase):
    name: str = Field(..., min_length=1, max_length=128, description="技能名称")
    is_enabled: bool = Field(default=True, description="是否启用")

    def create_dict(self):
        return self.model_dump(exclude_unset=True)


class SkillUpdate(SkillBase):
    skill_id: Optional[str] = Field(default=None, description="技能ID")


class SkillOut(BaseModel):
    id: str = Field(..., description="技能ID")
    name: str = Field(..., description="技能名称")
    description: Optional[str] = Field(default=None, description="技能描述")
    is_enabled: bool = Field(default=True, description="是否启用")
    config: Optional[dict[str, Any]] = Field(default=None, description="技能配置")
    created_time: datetime = Field(..., description="创建时间")
    updated_time: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True)


class DeveloperSkillForm(BaseModel):
    """开发者中心保存表单；资源文件本体由上传接口处理，元数据记录在 config 中。"""
    name: str = Field(..., min_length=1, max_length=128)
    class_id: str = Field(..., min_length=1, max_length=64)
    application_ids: list[str] = Field(default_factory=list)
    description: str = Field(..., min_length=1, max_length=1024)
    instructions: str = Field(..., min_length=1, max_length=100000)
    resource_ids: list[str] = Field(default_factory=list)
    resource_usage: str = Field(default="", max_length=10000)
    compatibility: str = Field(default="", max_length=500)
    technical_name: str = Field(default="", max_length=128)
    uploaded_resources: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_bases: list[dict[str, Any]] = Field(default_factory=list)
    skill_markdown: Optional[str] = Field(default=None, max_length=200000)


class DeveloperSkillOut(BaseModel):
    id: str
    name: str
    class_id: str
    application_ids: list[str]
    description: str
    instructions: str
    resource_ids: list[str]
    resource_usage: str
    compatibility: str
    technical_name: str
    uploaded_resources: list[dict[str, Any]]
    knowledge_bases: list[dict[str, Any]]
    skill_markdown: Optional[str] = None
    version: str
    status: str
    creator_id: str
    creator_name: str
    updated_at: datetime


class DeveloperDebugResult(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=128)
    build_id: Optional[str] = Field(default=None, max_length=64)
    status: Literal["passed", "failed", "timeout"]
    conversation_input: str = Field(default="", max_length=100000)
    request_document_count: int = Field(default=0, ge=0, le=10)
    result_file_name: Optional[str] = Field(default=None, max_length=255)
    result_byte_size: Optional[int] = Field(default=None, ge=0)
    error_message: Optional[str] = Field(default=None, max_length=10000)


class McpServerBase(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128, description="服务名称")
    description: Optional[str] = Field(default=None, description="服务描述")
    is_enabled: Optional[bool] = Field(default=None, description="是否启用")
    transport: Optional[Literal["stdio", "sse", "http"]] = Field(
        default=None, description="传输方式"
    )
    config: Optional[dict[str, Any]] = Field(default=None, description="连接配置")


class McpServerCreate(McpServerBase):
    name: str = Field(..., min_length=1, max_length=128, description="服务名称")
    is_enabled: bool = Field(default=True, description="是否启用")
    transport: Literal["stdio", "sse", "http"] = Field(
        default="stdio", description="传输方式"
    )

    def create_dict(self):
        return self.model_dump(exclude_unset=True)


class McpServerUpdate(McpServerBase):
    mcp_id: Optional[str] = Field(default=None, description="MCP服务ID")


class McpServerOut(BaseModel):
    id: str = Field(..., description="MCP服务ID")
    name: str = Field(..., description="服务名称")
    description: Optional[str] = Field(default=None, description="服务描述")
    is_enabled: bool = Field(default=True, description="是否启用")
    transport: str = Field(default="stdio", description="传输方式")
    config: Optional[dict[str, Any]] = Field(default=None, description="连接配置")
    created_time: datetime = Field(..., description="创建时间")
    updated_time: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True)
