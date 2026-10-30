# -*- coding: utf-8 -*-
import json
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field, field_validator

from enums.chat_session_enum import ChatMessageRole


def normalize_id_list(value) -> Optional[List[str]]:
    """统一 ID 列表（兼容 JSONField 与历史 LONGTEXT JSON 字符串）"""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else None
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def normalize_knowledge_base_ids(value) -> Optional[List[str]]:
    """统一知识库 ID 列表"""
    return normalize_id_list(value)


def normalize_skill_ids(value) -> Optional[List[str]]:
    """统一技能 ID 列表"""
    return normalize_id_list(value)


def normalize_mcp_ids(value) -> Optional[List[str]]:
    """统一 MCP 服务 ID 列表"""
    return normalize_id_list(value)


class ConversationBase(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255, description="对话标题")
    knowledge_base_ids: Optional[List[str]] = Field(
        default=None, description="关联知识库ID列表"
    )
    skill_ids: Optional[List[str]] = Field(
        default=None, description="关联技能ID列表"
    )
    mcp_ids: Optional[List[str]] = Field(
        default=None, description="关联MCP服务ID列表"
    )
    model_config_id: Optional[str] = Field(default=None, description="模型配置ID")


class ConversationCreate(ConversationBase):
    user_id: int = Field(..., description="用户ID")
    title: str = Field(default="新对话", max_length=255, description="对话标题")

    def create_dict(self):
        return self.model_dump(exclude_unset=True)


class ConversationUpdate(ConversationBase):
    conversation_id: Optional[str] = Field(default=None, description="对话ID")


class ConversationSelect(ConversationBase):
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=10, ge=10, description="每页数量")
    order: Optional[list] = Field(default=["-updated_time"], description="排序字段")


class ConversationOut(BaseModel):
    id: str = Field(..., description="对话ID")
    user_id: int = Field(..., description="用户ID")
    title: str = Field(..., description="对话标题")
    knowledge_base_ids: Optional[List[str]] = Field(
        default=None, description="关联知识库ID列表"
    )
    model_config_id: Optional[str] = Field(default=None, description="模型配置ID")
    skill_ids: Optional[List[str]] = Field(default=None, description="关联技能ID列表")
    mcp_ids: Optional[List[str]] = Field(default=None, description="关联MCP服务ID列表")
    created_time: datetime = Field(..., description="创建时间")
    updated_time: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("knowledge_base_ids", mode="before")
    @classmethod
    def parse_knowledge_base_ids(cls, v):
        return normalize_knowledge_base_ids(v)

    @field_validator("skill_ids", mode="before")
    @classmethod
    def parse_skill_ids(cls, v):
        return normalize_skill_ids(v)

    @field_validator("mcp_ids", mode="before")
    @classmethod
    def parse_mcp_ids(cls, v):
        return normalize_mcp_ids(v)


class ConversationDetail(ConversationOut):
    messages: list["MessageOut"] = Field(default_factory=list, description="消息列表")


class MessageBase(BaseModel):
    role: Optional[ChatMessageRole] = Field(default=None, description="消息角色")
    content: Optional[str] = Field(default=None, description="消息内容")
    prompt_tokens: Optional[int] = Field(default=None, description="输入Token数")
    completion_tokens: Optional[int] = Field(default=None, description="输出Token数")
    reasoning_tokens: Optional[int] = Field(default=None, description="推理Token数")
    process_trace: Optional[List[dict]] = Field(
        default=None,
        description="过程追踪(推理链/工具调用等)",
    )


class MessageCreate(MessageBase):
    conversation_id: str = Field(..., description="对话ID")
    role: ChatMessageRole = Field(..., description="消息角色")
    content: str = Field(..., min_length=1, description="消息内容")

    def create_dict(self):
        obj = self.model_dump(exclude_unset=True)
        if isinstance(obj.get("role"), ChatMessageRole):
            obj["role"] = obj["role"].value
        return obj


class MessageUpdate(MessageBase):
    message_id: Optional[int] = Field(default=None, description="消息ID")


class MessageSelect(MessageBase):
    conversation_id: Optional[str] = Field(default=None, description="对话ID")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=50, ge=10, description="每页数量")
    order: Optional[list] = Field(default=["created_time"], description="排序字段")


class TokenUsage(BaseModel):
    prompt_tokens: Optional[int] = Field(default=None, description="输入Token数(Prompt)")
    completion_tokens: Optional[int] = Field(default=None, description="输出Token数(Completion)")
    reasoning_tokens: Optional[int] = Field(default=None, description="推理Token数(Thinking/Reasoning)")
    total_tokens: Optional[int] = Field(default=None, description="Token总消耗量")


class ConversationBrief(BaseModel):
    id: str = Field(..., description="对话ID")
    title: str = Field(..., description="对话标题")


class ModelConfigBrief(BaseModel):
    id: Optional[str] = Field(default=None, description="模型配置ID")
    config_name: Optional[str] = Field(default=None, description="用户自定义配置名称")
    config_desc: Optional[str] = Field(default=None, description="配置说明")


class KnowledgeBaseBrief(BaseModel):
    id: str = Field(..., description="知识库ID")
    name: Optional[str] = Field(default=None, description="知识库名称")
    description: Optional[str] = Field(default=None, description="知识库描述")


class UserBrief(BaseModel):
    id: int = Field(..., description="用户ID")
    username: str = Field(..., description="用户账号")
    alias: str = Field(..., description="用户名称")


class ConversationStatSelect(BaseModel):
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=10, ge=1, le=100, description="每页数量")
    start_time: Optional[str] = Field(default=None, description="对话开始时间（按更新时间筛选）")
    end_time: Optional[str] = Field(default=None, description="对话结束时间（按更新时间筛选）")


class ConversationStatOut(BaseModel):
    conversation: ConversationBrief = Field(..., description="对话信息")
    model_config_info: Optional[ModelConfigBrief] = Field(
        default=None, description="模型配置"
    )
    knowledge_bases: List[KnowledgeBaseBrief] = Field(
        default_factory=list, description="关联知识库列表"
    )
    round_count: int = Field(default=0, description="对话轮次")
    token_usage: TokenUsage = Field(..., description="Token消耗量")
    user: UserBrief = Field(..., description="用户信息")


class MessageOut(BaseModel):
    id: int = Field(..., description="消息ID")
    role: ChatMessageRole = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")
    prompt_tokens: Optional[int] = Field(default=None, description="输入Token数(Prompt)")
    completion_tokens: Optional[int] = Field(default=None, description="输出Token数(Completion)")
    reasoning_tokens: Optional[int] = Field(default=None, description="推理Token数(Thinking/Reasoning)")
    process_trace: Optional[List[dict]] = Field(
        default=None,
        description="过程追踪(推理链/工具调用等)",
    )
    created_time: datetime = Field(..., description="创建时间")

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    conversation_id: Optional[str] = Field(default=None, description="对话ID")
    knowledge_base_ids: Optional[List[str]] = Field(
        default=None,
        description="关联知识库ID列表；传 [] 表示清空绑定，不传则沿用会话已存值",
    )
    model_config_id: Optional[str] = Field(default=None, description="模型配置ID")
    skill_ids: Optional[List[str]] = Field(
        default=None,
        description="关联技能ID列表；传 [] 表示清空绑定，不传则沿用会话已存值",
    )
    mcp_ids: Optional[List[str]] = Field(
        default=None,
        description="关联MCP服务ID列表；传 [] 表示清空绑定，不传则沿用会话已存值",
    )
    enable_thinking: bool = Field(default=False, description="是否开启深度思考模式")
