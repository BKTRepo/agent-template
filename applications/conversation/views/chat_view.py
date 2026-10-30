import json
import traceback

from fastapi import APIRouter, Depends, Query
from sse_starlette.sse import EventSourceResponse

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


@chat.post("/stream", summary="对话-流式问答")
async def chat_stream(
        req: ChatRequest,
        current_user: User = DependAuth,
        conversation_crud: ConversationCrud = Depends(get_conversation_crud),
):
    # 1. 准备阶段：同步操作，阻塞等待
    conv, model_config, chat_history, knowledge_base_ids = (
        await conversation_crud.prepare_for_chat(req, current_user)
    )
    conversation_id = conv.id

    # 2. 定义异步生成器：惰性执行，不立即运行
    async def event_generator():
        full_response = ""
        full_reasoning = ""
        usage_data = None

        # 2.1 发送元数据事件（第一个事件）
        yield {
            "event": "meta",
            "data": json.dumps({"type": "meta", "conversation_id": conversation_id}),
        }

        try:
            # 2.2 流式生成内容（核心）
            async for chunk in conversation_crud.stream_response(
                    req.question,
                    knowledge_base_ids,
                    chat_history,
                    model_config,
                    enable_thinking=req.enable_thinking,
            ):
                if chunk.get("type") == "reasoning":
                    token = chunk.get("content", "")
                    full_reasoning += token
                    yield {
                        "event": "reasoning",
                        "data": json.dumps({"type": "reasoning", "content": token}),
                    }
                elif chunk.get("type") == "content":
                    token = chunk.get("content", "")
                    full_response += token
                    yield {
                        "event": "token",
                        "data": json.dumps({"type": "token", "content": token}),
                    }
                elif chunk.get("type") == "usage":
                    usage_data = {
                        "prompt_tokens": chunk.get("prompt_tokens"),
                        "completion_tokens": chunk.get("completion_tokens"),
                        "reasoning_tokens": chunk.get("reasoning_tokens"),
                    }
        except Exception as e:
            print(f"[chat_stream] 错误: {e}")
            # 2.3 错误处理
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": str(e)}),
            }
            return

        process_trace = []
        if full_reasoning.strip():
            process_trace.append(
                ReasoningStep(content=full_reasoning, status="done").model_dump()
            )

        # 2.4 保存完整回复到数据库
        try:
            await conversation_crud.save_assistant_message(
                conversation_id,
                full_response,
                prompt_tokens=usage_data.get("prompt_tokens") if usage_data else None,
                completion_tokens=usage_data.get("completion_tokens") if usage_data else None,
                reasoning_tokens=usage_data.get("reasoning_tokens") if usage_data else None,
                process_trace=process_trace or None,
            )
        except Exception as e:
            print(f"[chat_stream] 保存消息失败: {e}")

        # 2.5 发送完成事件
        done_payload = {"type": "done", "content": full_response}
        if process_trace:
            done_payload["process_trace"] = process_trace
        if usage_data:
            done_payload["usage"] = usage_data
        yield {
            "event": "done",
            "data": json.dumps(done_payload),
        }

    # 3. 返回 SSE 响应
    # EventSourceResponse 接收异步生成器，开始流式传输
    return EventSourceResponse(event_generator())


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
