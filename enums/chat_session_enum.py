# -*- coding: utf-8 -*-
# AI 会话相关枚举：消息角色、后续可扩展会话状态、流式事件类型等。

from .base_enum_cls import StringEnum


class ChatMessageRole(StringEnum):
    """聊天消息角色"""

    USER = ("user", "用户")
    ASSISTANT = ("assistant", "助手")


class DocumentStatus(StringEnum):
    """文档上传与处理状态"""

    PROCESSING = ("processing", "处理中")
    COMPLETED = ("completed", "已完成")
    FAILED = ("failed", "失败")
    DELETING = ("deleting", "删除中")
    DELETE_FAILED = ("delete_failed", "删除失败")
