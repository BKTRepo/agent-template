# -*- coding: utf-8 -*-
"""RAG 回答采纳反馈快照。

反馈只保存会话和检索数据的独立快照，不建立会话外键，避免删除会话时
级联删除已经产生的采纳经验和审计记录。
"""

from tortoise import fields

from applications.jiayueyang.services.scaffold import ScaffoldModel


class RagAnswerFeedback(ScaffoldModel):
    """一条回答的当前采纳/取消采纳状态及其历史可复用快照。"""

    feedback_uid = fields.CharField(
        max_length=64, unique=True, description="对外稳定反馈编号",
    )
    # 故意使用普通整数，不使用 ForeignKey，保证会话删除不影响反馈快照。
    conversation_id = fields.BigIntField(
        null=True, index=True, description="来源会话 ID，可空",
    )
    assistant_message_seq = fields.IntField(
        null=True, description="被采纳回答在会话内的位置",
    )
    action = fields.CharField(
        max_length=16, default="accepted", index=True,
        description="当前动作: accepted/revoked",
    )
    original_query = fields.TextField(null=True, description="原始问题快照")
    resolved_query = fields.TextField(null=True, description="指代消解后的问题")
    rewritten_query = fields.TextField(null=True, description="中文规范查询")
    english_query = fields.TextField(null=True, description="英文检索词")
    sub_queries = fields.JSONField(default=list, description="子查询快照")
    answer_snapshot = fields.JSONField(default=dict, description="回答内容和状态快照")
    retrieval_snapshot = fields.JSONField(default=dict, description="检索和重排快照")
    related_doc_ids = fields.JSONField(default=list, description="相关文档 ID")
    related_chunk_ids = fields.JSONField(default=list, description="相关分块 ID")
    mapping_snapshot = fields.JSONField(default=list, description="本轮映射及来源快照")
    scope = fields.CharField(max_length=255, null=True, index=True, description="适用范围")
    index_status = fields.CharField(
        max_length=16, default="pending", index=True,
        description="经验索引状态: pending/synced/failed/delete_pending/delete_failed/deleted",
    )
    query_fingerprint = fields.CharField(
        max_length=64, null=True, index=True, description="规范化问题指纹",
    )
    mapping_extract_status = fields.CharField(
        max_length=16, default="pending", index=True,
        description="映射证据状态: pending/succeeded/no_candidate/failed/revoke_pending/revoked",
    )
    mapping_extract_error = fields.TextField(null=True, description="映射证据提取错误")
    operator = fields.CharField(max_length=64, null=True, description="操作人")
    created_time = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_time = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "rag_answer_feedback"
        table_description = "RAG 回答采纳反馈与检索快照"
        unique_together = (("conversation_id", "assistant_message_seq"),)
        indexes = (
            ("action", "index_status"),
            ("scope", "index_status"),
            ("action", "mapping_extract_status"),
        )
        ordering = ["-updated_time", "id"]
