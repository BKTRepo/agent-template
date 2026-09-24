# -*- coding: utf-8 -*-
"""对话历史接口 — 会话的新建 / 列表 / 重命名 / 删除, 以及会话消息读取。

路由约定（与 rag_view 一致）:
    - chat_business: 业务路由, 在 views/__init__.py 中并入 rag_secure_router,
      挂载处统一施加前缀 /api（鉴权开关就绪后随之生效）。

会话归属: 当前阶段全部挂在公共用户 "User" 名下（见 ConversationService）。
"""
from fastapi import APIRouter, Body, Depends

from applications.jiayueyang.dependencies import get_conversation_service
from applications.jiayueyang.schemas.chat_schema import (
    ConversationCreate,
    ConversationPin,
    ConversationRename,
)
from applications.jiayueyang.schemas.feedback_schema import FeedbackActionRequest
from applications.jiayueyang.services.feedback_service import feedback_service
from applications.jiayueyang.services.chat_service import ConversationService
from configure import LOGGER
from core.exceptions import NotFoundException, ParameterException
from core.responses import (
    FailureResponse,
    NotFoundResponse,
    ParameterResponse,
    SuccessResponse,
)

# 业务路由: 对话历史管理
chat_business = APIRouter()


@chat_business.put(
    "/conversations/{conversation_id}/messages/{message_seq}/feedback",
    summary="对话-采纳或取消采纳回答",
)
async def set_answer_feedback(
        conversation_id: int,
        message_seq: int,
        request: FeedbackActionRequest = Body(...),
):
    """按服务端消息生成或更新反馈快照，前端不提交答案和检索数据。"""
    try:
        data = await feedback_service.set_feedback(
            conversation_id, message_seq, request.action,
        )
        return SuccessResponse(data=data)
    except NotFoundException as exc:
        return NotFoundResponse(message=exc.message)
    except ParameterException as exc:
        return ParameterResponse(message=exc.message)
    except Exception as exc:
        LOGGER.error(f"更新回答采纳状态失败: {exc}")
        return FailureResponse(message="更新回答采纳状态失败, 请稍后重试")


@chat_business.get(
    "/conversations/{conversation_id}/messages/{message_seq}/feedback",
    summary="对话-查询回答采纳状态",
)
async def get_answer_feedback(conversation_id: int, message_seq: int):
    """供重新打开会话时恢复前端采纳按钮状态。"""
    try:
        data = await feedback_service.get_feedback(conversation_id, message_seq)
        return SuccessResponse(data=data or {
            "conversation_id": conversation_id,
            "message_seq": message_seq,
            "action": None,
            "effective": False,
        })
    except Exception as exc:
        LOGGER.error(f"读取回答采纳状态失败: {exc}")
        return FailureResponse(message="读取回答采纳状态失败, 请稍后重试")


@chat_business.get("/conversations", summary="对话-获取会话列表")
async def list_conversations(
        service: ConversationService = Depends(get_conversation_service),
):
    """获取公共用户的全部会话, 按最近活跃倒序。"""
    try:
        data = await service.list_conversations()
        return SuccessResponse(data=data, total=len(data))
    except Exception as e:
        LOGGER.error(f"获取会话列表失败: {e}")
        return FailureResponse(message="获取会话列表失败, 请稍后重试")


@chat_business.get("/conversations/search", summary="对话-搜索会话内容")
async def search_conversations(
        q: str = "",
        service: ConversationService = Depends(get_conversation_service),
):
    """按关键词搜索 AI 回答内容, 返回命中的（会话, 消息）列表, 供搜索弹窗展示与跳转定位。"""
    try:
        data = await service.search_messages(q)
        return SuccessResponse(data=data, total=len(data))
    except Exception as e:
        LOGGER.error(f"搜索会话失败: {e}")
        return FailureResponse(message="搜索会话失败, 请稍后重试")


@chat_business.post("/conversations", summary="对话-新建会话")
async def create_conversation(
        request: ConversationCreate = Body(default_factory=ConversationCreate),
        service: ConversationService = Depends(get_conversation_service),
):
    """新建一个空会话, 返回会话信息（id/title/时间）。"""
    try:
        data = await service.create_conversation(request.title)
        return SuccessResponse(data=data)
    except Exception as e:
        LOGGER.error(f"新建会话失败: {e}")
        return FailureResponse(message="新建会话失败, 请稍后重试")


@chat_business.get("/conversations/{conversation_id}/messages", summary="对话-获取会话消息")
async def get_conversation_messages(
        conversation_id: int,
        service: ConversationService = Depends(get_conversation_service),
):
    """读取指定会话的全部历史消息（按时间升序）。"""
    try:
        conv = await service.get_conversation(conversation_id)
        if conv is None:
            return NotFoundResponse(message="会话不存在或已删除")
        data = await service.get_messages(conversation_id)
        return SuccessResponse(data=data, total=len(data))
    except Exception as e:
        LOGGER.error(f"获取会话消息失败: {e}")
        return FailureResponse(message="获取会话消息失败, 请稍后重试")


@chat_business.post(
    "/conversations/{conversation_id}/messages/{message_index}/stop",
    summary="对话-停止生成中的消息",
)
async def stop_message_generation(
        conversation_id: int,
        message_index: int,
        service: ConversationService = Depends(get_conversation_service),
):
    """停止仍在生成的回答: 置为 interrupted 并保留已产出的内容。

    后台生成任务在下一次节流回写时感知到状态变化后自行收尾。
    消息不存在或并非生成中状态时返回失败。
    """
    try:
        stopped = await service.stop_generating_message(conversation_id, message_index)
        if not stopped:
            return NotFoundResponse(message="消息不存在或已结束生成")
        return SuccessResponse(message="已停止生成")
    except Exception as e:
        LOGGER.error(f"停止生成失败: {e}")
        return FailureResponse(message="停止生成失败, 请稍后重试")


@chat_business.patch("/conversations/{conversation_id}", summary="对话-重命名会话")
async def rename_conversation(
        conversation_id: int,
        request: ConversationRename = Body(...),
        service: ConversationService = Depends(get_conversation_service),
):
    """重命名指定会话。"""
    try:
        data = await service.rename_conversation(conversation_id, request.title)
        if data is None:
            return NotFoundResponse(message="会话不存在或已删除")
        return SuccessResponse(data=data)
    except Exception as e:
        LOGGER.error(f"重命名会话失败: {e}")
        return FailureResponse(message="重命名会话失败, 请稍后重试")


@chat_business.patch("/conversations/{conversation_id}/pin", summary="对话-置顶/取消置顶")
async def pin_conversation(
        conversation_id: int,
        request: ConversationPin = Body(...),
        service: ConversationService = Depends(get_conversation_service),
):
    """置顶或取消置顶指定会话（置顶会话在列表中优先展示）。"""
    try:
        data = await service.set_pinned(conversation_id, request.pinned)
        if data is None:
            return NotFoundResponse(message="会话不存在或已删除")
        return SuccessResponse(data=data)
    except Exception as e:
        LOGGER.error(f"置顶会话失败: {e}")
        return FailureResponse(message="置顶会话失败, 请稍后重试")


@chat_business.delete("/conversations/{conversation_id}", summary="对话-删除会话")
async def delete_conversation(
        conversation_id: int,
        service: ConversationService = Depends(get_conversation_service),
):
    """软删除指定会话（列表中不再展示）。"""
    try:
        deleted = await service.delete_conversation(conversation_id)
        if not deleted:
            return NotFoundResponse(message="会话不存在或已删除")
        return SuccessResponse(message="删除成功")
    except Exception as e:
        LOGGER.error(f"删除会话失败: {e}")
        return FailureResponse(message="删除会话失败, 请稍后重试")
