# -*- coding: utf-8 -*-
from tortoise import fields

from applications.base.services.scaffold import (
    ScaffoldModel,
    StateModel,
    TimestampMixin,
    unique_identify,
)
from enums.chat_session_enum import ChatMessageRole


class Conversation(ScaffoldModel, StateModel, TimestampMixin):
    """对话会话模型"""
    id = fields.CharField(default=unique_identify, max_length=64, pk=True, description="对话ID")
    user = fields.ForeignKeyField(
        "models.User",
        related_name="conversations",
        on_delete=fields.CASCADE,
        description="所属用户",
    )
    title = fields.CharField(default="新对话", max_length=255, description="对话标题")
    knowledge_base_ids = fields.JSONField(null=True, description="关联知识库ID列表")
    skill_ids = fields.JSONField(null=True, description="关联技能ID列表")
    mcp_ids = fields.JSONField(null=True, description="关联MCP服务ID列表")
    model_config = fields.ForeignKeyField(
        "models.ModelConfig",
        related_name="conversations",
        null=True,
        on_delete=fields.SET_NULL,
        description="所属模型配置",
    )
    messages: fields.ReverseRelation["Message"]

    class Meta:
        table = "keenrobot_conversations"


class Message(ScaffoldModel, StateModel, TimestampMixin):
    """聊天消息模型"""
    id = fields.IntField(pk=True, description="消息ID")
    conversation = fields.ForeignKeyField(
        "models.Conversation",
        related_name="messages",
        on_delete=fields.CASCADE,
        description="所属对话",
    )
    role = fields.CharEnumField(ChatMessageRole, max_length=20, description="消息角色")
    content = fields.TextField(description="消息内容")
    prompt_tokens = fields.IntField(null=True, description="输入Token数(Prompt)")
    completion_tokens = fields.IntField(null=True, description="输出Token数(Completion)")
    reasoning_tokens = fields.IntField(null=True, description="推理Token数(Thinking/Reasoning)")
    process_trace = fields.JSONField(null=True, description="过程追踪(推理链/工具调用等)")

    class Meta:
        table = "keenrobot_messages"
        ordering = ["created_time"]
