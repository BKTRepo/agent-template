# -*- coding: utf-8 -*-
"""采纳反馈产生的程序映射证据。

单次采纳只进入这张证据表，不直接写入程序映射表。达到独立证据阈值后，
聚合服务才会创建或更新 ``rag_term_mapping_learned`` 候选。
"""

from tortoise import fields

from applications.jiayueyang.services.scaffold import ScaffoldModel


class RagTermMappingEvidence(ScaffoldModel):
    """一条由采纳反馈提取出的、尚未确认的映射证据。"""

    evidence_id = fields.CharField(max_length=64, unique=True, description="证据稳定编号")
    feedback_uid = fields.CharField(max_length=64, index=True, description="来源采纳反馈")
    query_fingerprint = fields.CharField(max_length=64, index=True, description="规范化问题指纹")
    query_text = fields.TextField(description="用于判断独立证据的问题文本")
    original_query = fields.TextField(description="来源反馈中的原始问题")
    alias_text = fields.CharField(max_length=255, description="本条证据代表的用户说法")
    alias_normalized = fields.CharField(max_length=255, index=True, description="用户说法规范化键")
    mapping_key = fields.CharField(max_length=255, index=True, description="规范化中文标准词聚合键")
    canonical_zh = fields.CharField(max_length=255, description="候选中文标准词")
    aliases_zh = fields.JSONField(default=list, description="候选中文别名")
    official_en = fields.CharField(max_length=255, null=True, description="候选官方英文词")
    aliases_en = fields.JSONField(default=list, description="候选英文别名和缩写")
    scope = fields.CharField(max_length=255, null=True, index=True, description="适用范围")
    normalized_keys = fields.JSONField(default=list, description="候选规范化键")
    supporting_doc_ids = fields.JSONField(default=list, description="支持证据的文档 ID")
    supporting_chunk_ids = fields.JSONField(default=list, description="支持证据的分块 ID")
    extraction_confidence = fields.FloatField(default=0.0, description="单次提取置信度")
    extraction_payload = fields.JSONField(default=dict, description="模型原始提取快照")
    status = fields.CharField(
        max_length=16,
        default="valid",
        index=True,
        description="状态: valid/revoked/conflict/covered/no_candidate",
    )
    algorithm_version = fields.CharField(max_length=64, null=True, description="提取算法版本")
    error_message = fields.TextField(null=True, description="提取或校验错误")
    created_time = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_time = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "rag_term_mapping_evidence"
        table_description = "RAG 采纳反馈产生的程序映射证据"
        unique_together = (("feedback_uid", "mapping_key"),)
        indexes = (
            ("mapping_key", "status"),
            ("query_fingerprint", "status"),
            ("feedback_uid", "status"),
        )
        ordering = ["-updated_time", "id"]
