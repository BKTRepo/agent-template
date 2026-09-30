# -*- coding: utf-8 -*-
"""对话历史模型（会话 / 消息 / 检索详情, MySQL）。

原 rag_storage/conversations.json + retrieval_details.json 的持久化载体迁移:
- 会话与消息拆为两张表（一对多）, 消息以 seq 维护"会话内位置",
  与 JSON 时代的数组下标语义完全一致（停止生成 / 重新生成 / SSE 重连 /
  搜索跳转定位均依赖该下标, 前端契约不变）;
- 检索详情沿用"独立于对话内容"的既定要求（体积大且不属于对话内容）,
  单独建表, 以 (conversation_id, message_seq) 唯一定位;
- 消息只追加不删改序（重新生成就地改写内容不改 seq）, 故 seq 稳定;
  会话删除经外键级联清理消息与检索详情。

时间语义: created_time 由数据库自动维护; updated_time 由服务层显式刷新
（仅提问落盘 / 消息终态 / 重命名时更新——置顶等操作不刷新, 保持
"最近对话"排序语义与原实现一致）, 故不使用 auto_now。
"""
from tortoise import fields

from applications.jiayueyang.services.scaffold import ScaffoldModel

# 消息状态取值（与原 JSON 存储一致）
MSG_DONE = "done"
MSG_GENERATING = "generating"
MSG_INTERRUPTED = "interrupted"
MSG_TRUNCATED = "truncated"


class RagConversation(ScaffoldModel):
    """对话会话表。"""

    username = fields.CharField(
        max_length=64, default="User", index=True,
        description="归属用户（当前阶段恒为 User, 预留真实用户体系）",
    )
    title = fields.CharField(max_length=255, default="新对话", description="会话标题（首问自动截取）")
    pinned = fields.BooleanField(default=False, index=True, description="是否置顶")
    created_time = fields.DatetimeField(auto_now_add=True, description="创建时间")
    # updated_time 不用 auto_now: 置顶等操作不得刷新"最近活跃"排序时间,
    # 由服务层在提问落盘/消息终态/重命名时显式更新
    updated_time = fields.DatetimeField(null=True, description="最近活跃时间")
    # ---- 滚动摘要（长期记忆）----
    # 早期轮次被挤出近期窗口后压缩成的摘要, 注入时作为背景上下文;
    # 与 summary_up_to_seq 构成"摘要/窗口"无缝边界, 保证消息不丢
    memory_summary = fields.TextField(null=True, description="对话历史滚动摘要（早期轮次压缩）")
    summary_up_to_seq = fields.IntField(default=-1, description="摘要已覆盖到的消息 seq（-1=尚无摘要）")

    class Meta:
        table = "rag_conversation"
        table_description = "RAG 对话会话表"
        ordering = ["-pinned", "-updated_time"]


class RagConversationMessage(ScaffoldModel):
    """对话消息表（一问一答各一条, 只追加不删改序）。"""

    # 外键级联: 删除会话时数据库自动清理其全部消息
    conversation = fields.ForeignKeyField(
        "models.RagConversation", related_name="messages",
        on_delete=fields.CASCADE, description="所属会话",
    )
    # 会话内位置（0 起）: 等价 JSON 时代的数组下标, 对外即 message_index;
    # 唯一约束防并发问答轮次重复占位（写入在会话行锁内分配）
    seq = fields.IntField(description="会话内消息位置(0起, 对外即消息下标)")
    role = fields.CharField(max_length=16, description="角色: user/assistant")
    content = fields.TextField(default="", description="消息内容（生成中为增量累积）")
    status = fields.CharField(
        max_length=16, default=MSG_DONE, index=True,
        description="状态: done/generating/interrupted",
    )
    thinking_ms = fields.IntField(null=True, description="思考耗时(毫秒, 仅 AI 回答)")
    # created_time 不用 auto_now_add: 历史数据迁移需保留原始时间, 由服务层写入
    created_time = fields.DatetimeField(null=True, index=True, description="消息创建时间")

    class Meta:
        table = "rag_conversation_message"
        table_description = "RAG 对话消息表"
        unique_together = (("conversation_id", "seq"),)
        ordering = ["conversation_id", "seq"]


class RagConversationRetrieval(ScaffoldModel):
    """AI 回答的检索详情表（独立于对话内容存储, 重写生成时覆盖）。"""

    # 外键级联: 删除会话时数据库自动清理其检索详情
    conversation = fields.ForeignKeyField(
        "models.RagConversation", related_name="retrievals",
        on_delete=fields.CASCADE, description="所属会话",
    )
    message_seq = fields.IntField(description="对应消息在会话内的位置(seq)")
    detail = fields.JSONField(default=dict, description="检索详情(改写查询/召回分块等)")
    created_time = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_time = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "rag_conversation_retrieval"
        table_description = "RAG 对话检索详情表"
        unique_together = (("conversation_id", "message_seq"),)
