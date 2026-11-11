import json
import traceback

from fastapi import APIRouter, Depends, Query
from sse_starlette.sse import EventSourceResponse

from applications.conversation.exceptions import ConversationBusinessError
from applications.conversation.dependencies import get_conversation_crud
from applications.conversation.schemas.conversation_schema import ChatRequest
from applications.conversation.schemas.process_step_schema import ReasoningStep
from applications.conversation.services.conversation_crud import ConversationCrud
from applications.user.models.user_model import User
from configure import LOGGER
from core.exceptions import NotFoundException
from core.responses import (
    FailureResponse,
    ForbiddenResponse,
    NotFoundResponse,
    SuccessResponse,
)
from services import DependAuth

chat = APIRouter()


@chat.post("/stream", summary="知识库问答-完整检索链路流式回答")
async def chat_stream(req: ChatRequest, current_user: User = DependAuth,
                      conversation_crud: ConversationCrud = Depends(get_conversation_crud)):
    from applications.wrq.knowledge_base.services.query_service import start_query, replay
    turn = await start_query(req, current_user, conversation_crud)
    return EventSourceResponse(replay(turn.id, current_user.id))


@chat.get("/resume-query", summary="知识库问答-按任务编号恢复流式回答")
async def resume_query(run_id: str = Query(..., min_length=1, max_length=32),
                       after: int = Query(default=0, ge=0), current_user: User = DependAuth):
    from applications.wrq.knowledge_base.models.query_model import KnowledgeQueryTurn
    from applications.wrq.knowledge_base.services.query_service import replay
    if not await KnowledgeQueryTurn.filter(id=run_id, owner_id=current_user.id).exists():
        raise ConversationBusinessError("问答任务不存在或无权限")
    return EventSourceResponse(replay(run_id, current_user.id, after))


@chat.get("/get-query-detail", summary="知识库问答-查询本人检索证据和执行状态")
async def query_detail(run_id: str = Query(..., min_length=1, max_length=32), current_user: User = DependAuth):
    from applications.wrq.knowledge_base.models.query_model import KnowledgeQueryTurn
    turn = await KnowledgeQueryTurn.get_or_none(id=run_id, owner_id=current_user.id)
    if turn is None:
        raise ConversationBusinessError("问答任务不存在或无权限")
    return SuccessResponse(data=dict(run_id=turn.id, status=turn.status, answer=turn.answer,
                                    retrieval=turn.retrieval, error=turn.error))


@chat.get("/users/{user_id}/conversation-stats", summary="对话-按用户分页查询统计详情")
async def list_user_conversation_stats(
        user_id: int,
        page: int = Query(default=1, ge=1, description="页码"),
        page_size: int = Query(default=10, ge=1, le=100, description="每页数量"),
        start_time: str = Query(default=None, description="对话开始时间（按更新时间筛选，如 2026-06-01 00:00:00）"),
        end_time: str = Query(default=None, description="对话结束时间（按更新时间筛选，如 2026-06-12 23:59:59）"),
        current_user: User = DependAuth,
        conversation_crud: ConversationCrud = Depends(get_conversation_crud),
):
    """返回指定用户各对话的标题、模型配置、知识库、轮次、Token 消耗及用户信息"""
    if current_user.id != user_id and not current_user.is_superuser:
        return ForbiddenResponse(message="无权查看该用户的对话统计")

    try:
        total, items = await conversation_crud.list_conversation_stats_by_user(
            user_id,
            page=page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
        )
        data = [item.model_dump() for item in items]
        return SuccessResponse(data=data, total=total)
    except NotFoundException as e:
        return NotFoundResponse(message=e.message)
    except Exception as e:
        LOGGER.error(f"查询用户对话统计失败: {e}\n{traceback.format_exc()}")
        return FailureResponse(message=f"查询失败: {e}")
