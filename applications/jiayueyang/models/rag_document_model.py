# -*- coding: utf-8 -*-
from tortoise import fields

from applications.jiayueyang.services.scaffold import (
    ScaffoldModel,
    TimestampMixin,
)


class RagDocument(ScaffoldModel, TimestampMixin):
    """RAG 文档模型（文档管理页的唯一持久化载体, MySQL）。

    与原 rag_storage/doc_status.json 单条记录字段一一对应:
    - job_id 即原 JSON 主键（doc-<md5 前 16 位>）;
    - created_time/updated_time（TimestampMixin, 数据库自动维护）对应原
      created_at/updated_at, 由 to_response 统一格式化为
      "yyyy-MM-dd HH:mm:ss" 字符串（空值输出 ""）, 前端契约不变;
    - sidecar 为 docling 侧车四元组（meta/blocks/drawings/tables 路径）,
      以 JSON 列存储;
    - Celery 协调字段（celery_task_id/heartbeat_at/cancel_requested/resume）
      支撑跨进程进度回写与僵尸巡检（详见 services/rag_service.py::sweep_stale_documents）。

    文档删除采用“先标记 deleting、后清理产物、最后硬删除”的流程（见
    services/rag_service.py::delete_files_and_docs）。
    """

    # ---- 身份与基础信息 ----
    job_id = fields.CharField(max_length=64, unique=True, description="任务ID(doc-<md5前16位>)")
    # MySQL utf8mb4 默认排序规则(ci)下唯一约束为大小写不敏感, 与原 JSON 侧重名校验语义一致
    filename = fields.CharField(max_length=255, unique=True, description="文件名")
    status = fields.CharField(
        max_length=32, default="queued", index=True,
        description="处理状态: queued/splitting/parsing/terminology/analyzing/chunking/embedding/complete/failed/deleting",
    )
    # 属性名沿用代码与接口惯例 summary, 数据库列名按表设计要求为 abstract
    summary = fields.TextField(
        source_field="abstract", default="-",
        description="文档摘要(失败时存错误描述, 取消时为'用户取消')",
    )

    # ---- 输入输出路径（docling 产物）----
    input_path = fields.CharField(max_length=512, null=True, description="源文件留档路径(input/<job_id>/)")
    output_path = fields.CharField(max_length=512, null=True, description="产物目录(output/rag_upload/<job_id>/)")
    artifacts_file = fields.CharField(max_length=512, null=True, description="docling artifacts 目录路径")
    sidecar = fields.JSONField(default=dict, description="侧车文件四元组: meta/blocks/drawings/tables 路径")
    chunks_file = fields.CharField(max_length=512, null=True, description="分块产物路径")

    # ---- 解析配置 ----
    do_ocr = fields.BooleanField(default=False, description="是否启用 OCR")
    force_ocr = fields.BooleanField(default=False, description="是否强制 OCR")
    enable_vlm = fields.BooleanField(default=False, description="是否启用多模态(VLM)分析")
    chunk_strategy = fields.CharField(max_length=32, null=True, description="分块策略(旧记录兼容字段)")

    # ---- 进度 ----
    page_count = fields.IntField(null=True, description="PDF 页数")
    total_parts = fields.IntField(default=1, description="子文档总数")
    completed_parts = fields.IntField(default=0, description="已完成子文档数")
    terminology_total_batches = fields.IntField(default=1, description="术语抽取总批次")
    terminology_completed_batches = fields.IntField(default=0, description="术语抽取已完成批次")
    analyzing_stage_skipped = fields.BooleanField(default=False, description="是否跳过多模态分析阶段")

    # ---- Celery / 跨进程协调 ----
    celery_task_id = fields.CharField(max_length=64, null=True, index=True, description="Celery 任务ID(巡检判活用)")
    heartbeat_at = fields.DatetimeField(null=True, index=True, description="Worker 最近心跳时间(巡检容忍15分钟)")
    cancel_requested = fields.BooleanField(default=False, description="取消标记(守卫: 已取消文档拒绝进度覆盖)")
    resume = fields.BooleanField(default=False, description="重试续跑标记(完成后清除)")
    deleting_retry_count = fields.IntField(
        default=0,
        description="删除任务由巡检重新投递的次数（仅补偿投递时递增）",
    )
    deletion_retryable = fields.BooleanField(
        default=True,
        description="删除失败后是否允许定时巡检自动补偿",
    )
    deletion_error_type = fields.CharField(
        max_length=64,
        null=True,
        description="最近一次删除失败的异常类型",
    )

    # ---- 结果与错误 ----
    content_length = fields.IntField(null=True, description="清洗后 markdown 字符数")
    chunks_count = fields.IntField(null=True, description="分块数量")
    error_trace = fields.TextField(null=True, description="错误堆栈(尾部500字符)")

    # ---- 增量更新 ----
    file_sha256 = fields.CharField(
        max_length=64, null=True,
        description="最新版本源文件 SHA256(增量更新快速通道: 与上传文件一致则免重处理)",
    )
    is_updating = fields.BooleanField(
        default=False,
        description="增量更新处理中(更新期间旧版本向量持续服务, 到达终态后清除)",
    )
    update_history = fields.JSONField(
        null=True,
        description="增量更新历史: [{time, filename, reused, embedded}]",
    )

    # ---- 阶段计时 ----
    parse_start_time = fields.DatetimeField(null=True, description="解析开始时间")
    parse_end_time = fields.DatetimeField(null=True, description="解析结束时间")
    parse_duration = fields.FloatField(null=True, description="解析耗时(秒)")
    term_start_time = fields.DatetimeField(null=True, description="术语抽取开始时间")
    term_end_time = fields.DatetimeField(null=True, description="术语抽取结束时间")
    analyze_start_time = fields.DatetimeField(null=True, description="多模态分析开始时间")
    analyze_end_time = fields.DatetimeField(null=True, description="多模态分析结束时间")
    analyze_duration = fields.FloatField(null=True, description="多模态分析耗时(秒)")
    chunk_start_time = fields.DatetimeField(null=True, description="分块开始时间")
    chunk_end_time = fields.DatetimeField(null=True, description="分块结束时间")
    embed_start_time = fields.DatetimeField(null=True, description="嵌入开始时间")
    embed_end_time = fields.DatetimeField(null=True, description="嵌入结束时间")
    process_end_time = fields.DatetimeField(null=True, description="处理结束时间")

    class Meta:
        table = "rag_document"
        table_description = "RAG 文档表(文档管理页持久化载体)"
        ordering = ["-created_time"]
