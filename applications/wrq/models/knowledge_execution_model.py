"""仅在后端保存知识库运行范围及查询证据。"""
import uuid
from tortoise import fields, models


class KnowledgeExecution(models.Model):
    run_id = fields.CharField(max_length=128, pk=True)
    owner_id = fields.IntField(index=True)
    skill_id = fields.IntField()
    skill_version_id = fields.IntField()
    build_id = fields.CharField(max_length=64)
    scope = fields.JSONField()
    token_hash = fields.CharField(max_length=64, unique=True)
    expires_at = fields.DatetimeField()
    active = fields.BooleanField(default=True)
    class Meta:
        table = 'keenrobot_knowledge_executions'


class KnowledgeToolCall(models.Model):
    id = fields.CharField(max_length=32, pk=True, default=lambda: uuid.uuid4().hex)
    run_id = fields.CharField(max_length=128, index=True)
    owner_id = fields.IntField(index=True)
    query = fields.TextField()
    status = fields.CharField(max_length=16, default='running')
    matches = fields.JSONField(default=list)
    error_type = fields.CharField(max_length=128, null=True)
    duration_ms = fields.IntField(default=0)
    tool_call_id = fields.CharField(max_length=128, null=True)
    delivered_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    class Meta:
        table = 'keenrobot_knowledge_tool_calls'
