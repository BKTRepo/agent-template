"""Query-only persistence; no changes to document ingestion tables."""
import uuid
from tortoise import fields, models

class KnowledgeQueryTurn(models.Model):
    id = fields.CharField(pk=True, max_length=32, default=lambda: uuid.uuid4().hex)
    owner_id = fields.IntField(index=True)
    conversation_id = fields.CharField(max_length=64, index=True)
    status = fields.CharField(max_length=20, default='running')
    question = fields.TextField()
    answer = fields.TextField(default='')
    retrieval = fields.JSONField(default=dict)
    events = fields.JSONField(default=list)
    error = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    class Meta:
        table = 'keenrobot_knowledge_query_turns'

class KnowledgeConversationMemory(models.Model):
    conversation_id = fields.CharField(pk=True, max_length=64)
    summary = fields.TextField(default='')
    up_to_seq = fields.IntField(default=-1)
    class Meta:
        table = 'keenrobot_knowledge_conversation_memory'
