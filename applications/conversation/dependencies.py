# -*- coding: utf-8 -*-
from dataclasses import dataclass

from applications.conversation.services.conversation_crud import (
    ConversationCrud,
    MessageCrud,
)


@dataclass
class ConversationServices:
    """对话模块服务组合，用于需要多模型联动的业务场景。"""

    conversation: ConversationCrud
    message: MessageCrud


async def get_conversation_crud() -> ConversationCrud:
    """获取对话 CRUD 服务实例"""
    return ConversationCrud()


async def get_message_crud() -> MessageCrud:
    """获取消息 CRUD 服务实例"""
    return MessageCrud()


async def get_conversation_services() -> ConversationServices:
    """获取对话模块组合服务"""
    return ConversationServices(
        conversation=ConversationCrud(),
        message=MessageCrud(),
    )
