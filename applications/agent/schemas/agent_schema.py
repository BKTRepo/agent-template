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
