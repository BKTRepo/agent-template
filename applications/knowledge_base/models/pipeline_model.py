# -*- coding: utf-8 -*-
"""流水线运行状态 / 历史消息模型（MySQL）。

原 rag_storage/pipeline_state.json + pipeline_history.jsonl 的持久化载体迁移:
- 运行状态（流水线启动时间）为全局单例, 以单行表承载——Web 进程与
  Celery Worker 进程共享 MySQL, 行级 UPDATE 天然原子, JSON 时代的
  portalocker 跨进程文件锁随之退役;
- 历史消息为只追加序列（原 JSONL 逐行追加）, 以自增 id 维护先后顺序,
  读取取最近 N 条; 超限裁剪改由 CRUD 层按条数惰性执行（替代原"整文件
  重写压缩"）。

时间语义: 历史消息 created_time 由数据库自动维护（auto_now_add）;
对外展示沿用原契约 "[HH:MM:SS] 消息"（仅取时分秒, 与原 JSONL 的
time-only 记录口径一致）。
"""
from tortoise import fields

from applications.base.services.scaffold import ScaffoldModel


class RagPipelineState(ScaffoldModel):
    """流水线运行状态表（单行）。

    仅承载流水线启动时间 start_time: 流水线开始处理时写入, 结束/取消时清空。
    表内约定至多一行, 由 CRUD 层 get-or-create 维护。
    """

    start_time = fields.DatetimeField(null=True, description="流水线启动时间（空闲为 NULL）")
    updated_time = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "rag_pipeline_state"
        table_description = "RAG 流水线运行状态表（单行）"


class RagPipelineHistory(ScaffoldModel):
    """流水线历史消息表（只追加, 读取取最近 N 条）。"""

    message = fields.TextField(description="历史消息内容")
    # created_time 不用 auto_now_add: 历史数据迁移需保留原始时分秒, 由 CRUD/
    # 迁移脚本显式写入（与 RagConversationMessage 同口径）
    created_time = fields.DatetimeField(null=True, index=True, description="消息时间")

    class Meta:
        table = "rag_pipeline_history"
        table_description = "RAG 流水线历史消息表"
        ordering = ["id"]
