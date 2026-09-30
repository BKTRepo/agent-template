# -*- coding: utf-8 -*-
from tortoise import fields

from applications.jiayueyang.services.scaffold import ScaffoldModel


class LLMCallLog(ScaffoldModel):
    """LLM 调用统计表 — 每次模型调用一行, 记录耗时/Token 用量/完整输入输出。

    用途: 排查"回答慢"时区分我们代码的耗时与模型自身的耗时, 并留存模型
    实际收到与生成的完整文本（复现问题、核算成本）。

    写入方: applications/jiayueyang/rag/llm.py 的 _chat_completion_inner
    （全项目 LLM 调用的唯一出口）, 以 fire-and-forget 方式异步落库——
    落库失败只记 warning, 绝不影响业务调用。

    与对话消息表的分工: rag_conversation_message 存对话内容与 thinking_ms
    （用户体感）, 本表存模型侧明细（含术语抽取/查询改写等非对话调用）,
    两者按时间轴对照即可定位瓶颈。
    """

    # ---- 调用身份 ----
    model = fields.CharField(max_length=128, description="模型名")
    scene = fields.CharField(
        max_length=64, null=True,
        description="调用场景(预留列, 当前恒为空; 后续可在调用点补传以区分最终回答/术语抽取/查询改写)",
    )
    stream = fields.BooleanField(description="是否流式调用")
    success = fields.BooleanField(description="调用是否成功")
    error_message = fields.TextField(null=True, description="失败时的错误摘要")

    # ---- 耗时 ----
    start_at = fields.DatetimeField(index=True, description="调用开始时间")
    end_at = fields.DatetimeField(null=True, description="调用结束时间")
    total_ms = fields.IntField(null=True, description="总耗时(毫秒)")
    first_token_ms = fields.IntField(null=True, description="首 Token 耗时(毫秒), 仅流式有值")

    # ---- Token 用量 ----
    prompt_tokens = fields.IntField(null=True, description="输入 Token 数")
    completion_tokens = fields.IntField(null=True, description="输出 Token 数")
    total_tokens = fields.IntField(null=True, description="总 Token 数")

    # ---- 完整输入输出 ----
    prompt_text = fields.TextField(description="模型实际收到的完整输入(messages 的 JSON)")
    completion_text = fields.TextField(null=True, description="模型实际生成的完整输出(流式为逐块拼接)")
    prompt_chars = fields.IntField(default=0, description="输入字符数(便于按体积排序, 免解析 JSON)")
    completion_chars = fields.IntField(default=0, description="输出字符数")

    created_time = fields.DatetimeField(auto_now_add=True, description="落库时间")

    class Meta:
        table = "llm_call_log"
        table_description = "LLM 调用统计表(耗时/Token/完整输入输出)"
        ordering = ["-start_at"]
        # 复合索引支撑最常见的查询: 某模型近一段时间的调用明细
        indexes = (("model", "start_at"),)
