# -*- coding: utf-8 -*-
"""术语映射模型。

用户上传的权威映射和程序根据采纳反馈归纳的映射必须分表保存：
- RagTermMappingSource 只能由上传/管理流程写入；
- RagTermMappingLearned 只能由反馈归纳流程写入，达到证据阈值后自动激活；管理接口仅用于纠错或停用。

两张表不互相覆盖。查询服务按来源和状态读取，程序归纳数据即使被审核激活，
也不会复制回用户权威表。
"""

from tortoise import fields

from applications.jiayueyang.services.scaffold import ScaffoldModel


class RagTermMappingSource(ScaffoldModel):
    """用户上传的权威术语映射。"""

    mapping_id = fields.CharField(
        max_length=64, unique=True, description="对外稳定映射编号",
    )
    mapping_key = fields.CharField(
        max_length=255, unique=True, description="规范化标准词与适用范围生成的用户映射幂等键",
    )
    canonical_zh = fields.CharField(max_length=255, description="中文标准词")
    aliases_zh = fields.JSONField(default=list, description="中文别名数组")
    official_en = fields.CharField(
        max_length=255, null=True, description="官方英文词",
    )
    aliases_en = fields.JSONField(default=list, description="英文别名和缩写数组")
    scope = fields.CharField(max_length=255, null=True, index=True, description="适用范围")
    note = fields.TextField(null=True, description="参考出处或补充说明")
    raw_payload = fields.JSONField(default=dict, description="上传原始行快照")
    normalized_keys = fields.JSONField(default=list, description="规范化匹配键数组")
    status = fields.CharField(
        max_length=16, default="enabled", index=True,
        description="状态: enabled/disabled",
    )
    upload_batch_id = fields.CharField(
        max_length=64, index=True, description="上传批次编号",
    )
    source_file = fields.CharField(max_length=255, null=True, description="来源文件名")
    source_row = fields.IntField(null=True, description="来源文件行号")
    version = fields.IntField(default=1, description="业务记录版本")
    created_by = fields.CharField(max_length=64, null=True, description="上传人")
    updated_by = fields.CharField(max_length=64, null=True, description="最后修改人")
    created_time = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_time = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "rag_term_mapping_source"
        table_description = "RAG 用户上传的权威术语映射表"
        indexes = (
            ("canonical_zh", "scope"),
            ("status", "scope"),
        )
        ordering = ["-updated_time", "id"]


class RagTermMappingLearned(ScaffoldModel):
    """程序从采纳反馈归纳出的术语映射；达到证据阈值后自动激活。"""

    learned_mapping_id = fields.CharField(
        max_length=64, unique=True, description="程序映射稳定编号",
    )
    mapping_key = fields.CharField(
        max_length=255, unique=True, description="规范化中文标准词生成的程序映射聚合键",
    )
    canonical_zh = fields.CharField(max_length=255, description="归纳的中文标准词")
    aliases_zh = fields.JSONField(default=list, description="归纳的中文别名数组")
    official_en = fields.CharField(
        max_length=255, null=True, description="归纳的官方英文词",
    )
    aliases_en = fields.JSONField(default=list, description="归纳的英文别名和缩写数组")
    scope = fields.CharField(max_length=255, null=True, index=True, description="适用范围")
    normalized_keys = fields.JSONField(default=list, description="规范化匹配键数组")
    evidence_count = fields.IntField(default=0, description="独立采纳证据数量")
    confidence = fields.FloatField(default=0.0, description="归纳置信度")
    status = fields.CharField(
        max_length=16, default="active", index=True,
        description="状态: active/disabled；candidate/rejected 仅兼容历史或管理操作",
    )
    source_feedback_ids = fields.JSONField(
        default=list, description="来源反馈记录 ID 数组",
    )
    algorithm_version = fields.CharField(
        max_length=64, null=True, description="归纳规则或模型版本",
    )
    reviewed_by = fields.CharField(max_length=64, null=True, description="审核人")
    reviewed_time = fields.DatetimeField(null=True, description="审核时间")
    created_time = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_time = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "rag_term_mapping_learned"
        table_description = "RAG 程序归纳术语映射表"
        indexes = (
            ("canonical_zh", "scope"),
            ("status", "scope"),
        )
        ordering = ["-updated_time", "id"]
