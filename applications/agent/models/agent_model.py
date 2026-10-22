# -*- coding: utf-8 -*-
from tortoise import fields
from applications.agent.skill_names import skill_name_key

from applications.base.services.scaffold import (
    ScaffoldModel,
    StateModel,
    TimestampMixin,
    unique_identify,
)


class Skill(ScaffoldModel, StateModel, TimestampMixin):
    """Agent 技能定义"""
    id = fields.CharField(
        default=unique_identify, max_length=64, pk=True, description="技能ID"
    )
    name = fields.CharField(max_length=128, description="技能名称")
    name_key = fields.CharField(max_length=64, null=True, unique=True,
                               description="未删除技能的规范化名称摘要，删除后为空")
    description = fields.TextField(null=True, description="技能描述")
    user = fields.ForeignKeyField(
        "models.User",
        related_name="skills",
        on_delete=fields.CASCADE,
        description="所属用户",
    )
    is_enabled = fields.BooleanField(default=True, description="是否启用")
    config = fields.JSONField(null=True, description="技能配置(提示词/参数等)")

    class Meta:
        table = "keenrobot_skills"

    async def save(self, using_db=None, update_fields=None, **kwargs):
        # create / update / soft-delete / restore 共用同一约束；禁止前端指定键。
        self.name = self.name.strip()
        self.name_key = None if self.state == 1 else skill_name_key(self.name)
        if update_fields is not None:
            update_fields = list(set(update_fields) | {"name", "name_key"})
        return await super().save(using_db=using_db, update_fields=update_fields, **kwargs)


class McpServer(ScaffoldModel, StateModel, TimestampMixin):
    """MCP 服务配置"""
    id = fields.CharField(
        default=unique_identify, max_length=64, pk=True, description="MCP服务ID"
    )
    name = fields.CharField(max_length=128, description="服务名称")
    description = fields.TextField(null=True, description="服务描述")
    user = fields.ForeignKeyField(
        "models.User",
        related_name="mcp_servers",
        on_delete=fields.CASCADE,
        description="所属用户",
    )
    is_enabled = fields.BooleanField(default=True, description="是否启用")
    transport = fields.CharField(
        max_length=32, default="stdio", description="传输方式(stdio/sse/http)"
    )
    config = fields.JSONField(null=True, description="连接配置")

    class Meta:
        table = "keenrobot_mcp_servers"
