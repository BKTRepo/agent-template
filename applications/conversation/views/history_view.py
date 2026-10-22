# -*- coding: utf-8 -*-
import traceback

from fastapi import APIRouter, Depends

from applications.conversation.dependencies import get_conversation_crud
from applications.conversation.schemas.conversation_schema import (
    ConversationDetail,
    ConversationOut,
)
from applications.conversation.services.conversation_crud import ConversationCrud
from applications.user.models.user_model import User
from configure import LOGGER
from core.exceptions import NotFoundException
from core.responses import SuccessResponse, FailureResponse, NotFoundResponse
from services import DependAuth

history = APIRouter()


@history.get("/", summary="对话历史-查询对话列表")
async def list_conversations(
        current_user: User = DependAuth,
        conversation_crud: ConversationCrud = Depends(get_conversation_crud),
):
    try:
        items = await conversation_crud.list_conversations(current_user)
        data = [
            ConversationOut.model_validate(item).model_dump()
            for item in items
        ]
        return SuccessResponse(data=data, total=len(data))
    except Exception as e:
        LOGGER.error(f"查询对话列表失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@history.get("/{conversation_id}", summary="对话历史-按id查询对话详情")
async def get_conversation(
        conversation_id: str,
        current_user: User = DependAuth,
        conversation_crud: ConversationCrud = Depends(get_conversation_crud),
):
    try:
        conv = await conversation_crud.get_with_messages(conversation_id, current_user.id)
        if not conv:
            return NotFoundResponse(message="对话不存在")
        data = ConversationDetail.model_validate(conv).model_dump()
        return SuccessResponse(data=data)
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询对话详情失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")


@history.delete("/{conversation_id}", summary="对话历史-按id删除对话")
async def delete_conversation(
        conversation_id: str,
        current_user: User = DependAuth,
        conversation_crud: ConversationCrud = Depends(get_conversation_crud),
):
    try:
        await conversation_crud.delete_conversation(conversation_id, current_user)
        return SuccessResponse(message="已删除")
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"删除对话失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"删除失败: {e}")


@history.delete("/", summary="对话历史-清空所有对话")
async def clear_all_conversations(
        current_user: User = DependAuth,
        conversation_crud: ConversationCrud = Depends(get_conversation_crud),
):
    try:
        await conversation_crud.clear_all(current_user)
        return SuccessResponse(message="已清空所有对话")
    except Exception as e:
        LOGGER.error(f"清空对话失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"清空失败: {e}")
