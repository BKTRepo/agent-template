"""悬浮对话台模型，统计记录独立于会话清理周期。"""

import uuid

from tortoise import fields, models


def conversation_id():
    return uuid.uuid4().hex


class ChatConversation(models.Model):
    id = fields.CharField(max_length=64, pk=True, default=conversation_id, description="会话ID")
    user = fields.ForeignKeyField("models.User", related_name="floating_chats", on_delete=fields.CASCADE, description="所属用户ID")
    title = fields.CharField(max_length=255, default="新对话", description="会话标题")
    history_path = fields.CharField(max_length=160, default="", description="会话 JSONL 在历史目录下的相对路径")
    favorite = fields.BooleanField(default=False, description="是否收藏")
    generation = fields.IntField(default=1, description="上下文代次，清空会话时递增")
    skills = fields.JSONField(default=list, description="当前加载的技能ID列表")
    knowledge_bases = fields.JSONField(default=list, description="当前加载的知识库ID列表")
    model = fields.CharField(max_length=128, null=True, description="当前选择的模型标识，空值表示自动选择")
    summary_message_id = fields.IntField(null=True, description="摘要已覆盖的最后一条消息ID")
    state = fields.SmallIntField(default=0, description="会话状态：0正常，1已删除")
    created_time = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_time = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "chat_conversations"
        table_description = "悬浮对话台会话表"
        indexes = (("user_id", "state", "updated_time"),)


class ChatMessage(models.Model):
    id = fields.IntField(pk=True, description="消息ID")
    conversation = fields.ForeignKeyField("models.ChatConversation", related_name="messages", on_delete=fields.CASCADE, description="所属会话ID")
    generation = fields.IntField(description="消息所属的上下文代次")
    role = fields.CharField(max_length=16, description="消息角色：user用户，assistant助手")
    unread = fields.BooleanField(default=False, description="AI消息是否未读")
    created_time = fields.DatetimeField(auto_now_add=True, description="消息创建时间")

    class Meta:
        table = "chat_messages"
        table_description = "悬浮对话台消息表"
        indexes = (("conversation_id", "generation", "id"),)


class ChatTask(models.Model):
    id = fields.BigIntField(pk=True, description="对话任务ID")
    conversation = fields.ForeignKeyField("models.ChatConversation", related_name="tasks", on_delete=fields.CASCADE, description="所属会话ID")
    generation = fields.IntField(description="任务所属的上下文代次")
    user_message_id = fields.IntField(description="触发本次任务的用户消息ID")
    assistant_message_id = fields.IntField(null=True, description="本次任务对应的AI消息ID")
    retry_of_task_id = fields.BigIntField(null=True, description="重试时关联的原任务ID")
    model = fields.CharField(max_length=128, null=True, description="本次任务使用的模型标识")
    status = fields.CharField(max_length=16, default="pending", description="任务状态：pending待执行、running执行中、cancelling取消中、recovering恢复中、success成功、failed失败、cancelled已取消")
    error = fields.TextField(null=True, description="任务失败或恢复异常原因")
    started_at = fields.DatetimeField(null=True, description="任务开始时间")
    finished_at = fields.DatetimeField(null=True, description="任务结束时间")
    heartbeat_at = fields.DatetimeField(null=True, description="最近一次任务心跳时间")
    worker_host = fields.CharField(max_length=255, null=True, description="执行任务的主机名，用于异常恢复")
    created_time = fields.DatetimeField(auto_now_add=True, description="任务创建时间")

    class Meta:
        table = "chat_tasks"
        table_description = "悬浮对话台生成任务表"
        indexes = (("conversation_id", "generation", "status"),)


class ChatFeedback(models.Model):
    id = fields.BigIntField(pk=True, description="评价ID")
    message = fields.ForeignKeyField("models.ChatMessage", related_name="feedback", on_delete=fields.CASCADE, description="被评价的AI消息ID")
    user = fields.ForeignKeyField("models.User", related_name="chat_feedback", on_delete=fields.CASCADE, description="评价用户ID")
    rating = fields.CharField(max_length=8, description="评价类型：like点赞，dislike点踩")
    reason = fields.TextField(null=True, description="点踩原因")
    created_time = fields.DatetimeField(auto_now_add=True, description="评价创建时间")
    updated_time = fields.DatetimeField(auto_now=True, description="评价更新时间")

    class Meta:
        table = "chat_feedback"
        table_description = "悬浮对话台消息评价表"
        unique_together = (("message_id", "user_id"),)


class ChatArtifact(models.Model):
    id = fields.BigIntField(pk=True, description="产物ID")
    task = fields.ForeignKeyField("models.ChatTask", related_name="artifacts", on_delete=fields.CASCADE, description="生成产物的任务ID")
    file_name = fields.CharField(max_length=255, description="产物展示文件名")
    storage_key = fields.CharField(max_length=512, description="产物相对存储路径")
    artifact_type = fields.CharField(max_length=24, description="产物类型：test_case测试用例，other其他文件")
    count_status = fields.CharField(max_length=16, default="pending", description="统计状态：pending待统计、counted已统计、failed失败待重试、needs_review待处理")
    count_error = fields.TextField(null=True, description="产物统计失败原因")
    retry_count = fields.IntField(default=0, description="产物统计已重试次数")
    created_time = fields.DatetimeField(auto_now_add=True, description="产物记录创建时间")

    class Meta:
        table = "chat_artifacts"
        table_description = "悬浮对话台生成产物表"


class ChatSkillCall(models.Model):
    id = fields.BigIntField(pk=True, description="技能调用记录ID")
    task_id = fields.BigIntField(index=True, description="触发调用的对话任务ID")
    skill_id = fields.IntField(index=True, description="实际调用的技能ID")
    call_id = fields.CharField(max_length=64, unique=True, description="单次技能调用唯一标识，用于去重")
    created_time = fields.DatetimeField(auto_now_add=True, description="技能调用时间")

    class Meta:
        table = "chat_skill_calls"
        table_description = "悬浮对话台技能调用统计表"


class ChatArtifactCount(models.Model):
    id = fields.BigIntField(pk=True, description="产物统计记录ID")
    artifact_id = fields.BigIntField(unique=True, description="原产物ID，用于统计去重")
    quantity = fields.IntField(null=True, description="计入的产物数量，统计失败时为空")
    status = fields.CharField(max_length=16, default="counted", description="统计结果：counted成功，failed失败")
    error = fields.TextField(null=True, description="产物已清理后保留的统计失败原因")
    created_time = fields.DatetimeField(auto_now_add=True, description="统计记录创建时间")

    class Meta:
        table = "chat_artifact_counts"
        table_description = "悬浮对话台产物数量统计表"


class ChatCleanup(models.Model):
    id = fields.BigIntField(pk=True, description="清理任务ID")
    conversation_id = fields.CharField(max_length=64, description="待清理的会话ID")
    generation = fields.IntField(description="待清理的上下文代次")
    status = fields.CharField(max_length=16, default="pending", description="清理状态：pending待清理、failed失败待重试、completed完成")
    error = fields.TextField(null=True, description="最近一次清理失败原因")
    retry_count = fields.IntField(default=0, description="清理失败次数")
    created_time = fields.DatetimeField(auto_now_add=True, description="清理任务创建时间")

    class Meta:
        table = "chat_cleanup"
        table_description = "悬浮对话台历史数据清理任务表"
        unique_together = (("conversation_id", "generation"),)
