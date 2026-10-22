# -*- coding: utf-8 -*-
from tortoise import fields, models
from applications.agent.skill_names import skill_name_key

from applications.base.services.scaffold import (
    ScaffoldModel,
    StateModel,
    TimestampMixin,
    unique_identify,
)


class DeveloperSkillClass(models.Model):
    id = fields.CharField(max_length=64, pk=True)
    name = fields.CharField(max_length=128, unique=True)
    sort_order = fields.IntField(default=0)
    is_enabled = fields.BooleanField(default=True)

    class Meta:
        table = "keenrobot_skill_classes"


class DeveloperApplication(models.Model):
    id = fields.CharField(max_length=64, pk=True)
    name = fields.CharField(max_length=128, unique=True)
    sort_order = fields.IntField(default=0)
    is_enabled = fields.BooleanField(default=True)

    class Meta:
        table = "keenrobot_applications"


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
    display_status = fields.CharField(max_length=16, default="DRAFT", description="开发者中心状态")
    current_version_id = fields.CharField(max_length=64, null=True, description="当前版本ID")
    current_revision = fields.IntField(default=1, description="当前修订次数")
    last_debug_run_id = fields.CharField(max_length=128, null=True, description="最近调试运行ID")
    last_debug_passed_at = fields.DatetimeField(null=True, description="最近调试通过时间")
    published_at = fields.DatetimeField(null=True, description="上线时间")
    offline_at = fields.DatetimeField(null=True, description="下线时间")
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


class SkillVersion(models.Model):
    """开发者中心的 Skill 保存版本。文件和沙箱结果均按此版本关联。"""
    id = fields.CharField(max_length=64, pk=True)
    skill_id = fields.CharField(max_length=64, index=True)
    version = fields.CharField(max_length=32)
    revision = fields.IntField()
    skill_class_id = fields.CharField(max_length=64)
    application_id = fields.CharField(max_length=64, null=True)
    description = fields.CharField(max_length=1024)
    instructions = fields.TextField()
    resource_usage = fields.TextField(null=True)
    compatibility = fields.CharField(max_length=500, null=True)
    skill_markdown = fields.TextField(null=True)
    build_id = fields.CharField(max_length=64, null=True)
    package_storage_key = fields.CharField(max_length=512, null=True)
    manifest_hash = fields.CharField(max_length=64, null=True)
    created_by = fields.BigIntField()
    created_time = fields.DatetimeField(auto_now_add=True)
    updated_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "keenrobot_skill_versions"
        unique_together = (("skill_id", "version"),)


class SkillDebugRun(models.Model):
    """同事沙箱服务返回的运行结果索引；结果文件仍由沙箱服务保存。"""
    id = fields.CharField(max_length=64, pk=True)
    run_id = fields.CharField(max_length=128, unique=True)
    skill_id = fields.CharField(max_length=64, index=True)
    skill_version_id = fields.CharField(max_length=64, index=True)
    build_id = fields.CharField(max_length=64, null=True)
    status = fields.CharField(max_length=16, default="QUEUED")
    conversation_input = fields.TextField(null=True)
    request_document_count = fields.IntField(default=0)
    resource_manifest_hash = fields.CharField(max_length=64, null=True)
    result_storage_key = fields.CharField(max_length=512, null=True)
    result_file_name = fields.CharField(max_length=255, null=True)
    result_byte_size = fields.BigIntField(null=True)
    error_code = fields.CharField(max_length=64, null=True)
    error_message = fields.TextField(null=True)
    started_at = fields.DatetimeField(null=True)
    finished_at = fields.DatetimeField(null=True)
    created_by = fields.BigIntField()
    created_time = fields.DatetimeField(auto_now_add=True)
    updated_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "keenrobot_skill_debug_runs"


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
