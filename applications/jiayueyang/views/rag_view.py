# -*- coding: utf-8 -*-
"""RAG 文档智能解析与问答接口。

提供文档上传解析、流水线管控与 RAG 问答（含 SSE 流式）等接口。
路由按模板约定拆分为两组（见 views/__init__.py）:
- rag_health: 公开路由（健康检查）
- rag_business: 业务路由（挂载处统一施加 DependAuth 鉴权）
"""
import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from sse_starlette.sse import EventSourceResponse

from applications.jiayueyang.dependencies import (
    get_conversation_service,
    get_rag_document_service,
    get_rag_pipeline_service,
)
from applications.jiayueyang.models.conversation_model import MSG_DONE, MSG_INTERRUPTED, MSG_TRUNCATED
from applications.jiayueyang.rag.memory import (
    compute_window_and_overflow,
    llm_fold_summary,
    recall_turn_memory,
    upsert_turn_memory,
)
from applications.jiayueyang.schemas.rag_schema import (
    QuerySelect,
    RetryConvert,
    RollbackConvert,
    UpdateSummary,
)
from applications.jiayueyang.services.chat_service import (
    ConversationService,
    read_message_status,
    save_retrieval_detail,
    update_message,
)
from applications.jiayueyang.services.rag_pipeline import RagPipelineService
from applications.jiayueyang.services.rag_service import RagDocumentService
from common.file_utils import read_upload_with_cap
from configure import LOGGER, PROJECT_CONFIG
from core.exceptions import (
    DataAlreadyExistsException,
    NotFoundException,
    ParameterException,
)
from core.responses import (
    DataAlreadyExistsResponse,
    FailureResponse,
    NotFoundResponse,
    ParameterResponse,
    SuccessResponse,
)

# 公开路由: 健康检查类接口
rag_health = APIRouter()
# 业务路由: 文档解析 / 流水线管控 / RAG 问答
rag_business = APIRouter()


# ==================== 文档管理接口 ====================

@rag_business.get("/documents", summary="RAG-获取所有文档列表")
async def list_documents(
        document_service: RagDocumentService = Depends(get_rag_document_service),
):
    """获取全部已上传文档及其处理状态（服务端为准）。"""
    try:
        data = await document_service.get_all_documents()
        return SuccessResponse(data=data, total=len(data))
    except Exception as e:
        LOGGER.error(f"获取文档列表失败: {e}")
        return FailureResponse(message="获取文档列表失败, 请稍后重试")


@rag_business.post("/convert", summary="RAG-上传 PDF 进行转换")
async def convert_pdf(
        file: UploadFile = File(...),
        do_ocr: bool = Form(True),
        force_ocr: bool = Form(False),
        enable_vlm: bool = Form(False),
        pipeline_service: RagPipelineService = Depends(get_rag_pipeline_service),
):
    """提交 PDF 转换任务, 立即返回 job_id, 由 Celery Worker 内的原生 docling 离线解析。"""
    try:
        # 限额流式读取: 中间件已按 Content-Length 前置拒绝, 此处防御伪造头/分块传输
        max_upload_bytes = PROJECT_CONFIG.RAG_MAX_UPLOAD_MB * 1024 * 1024
        file_bytes = await read_upload_with_cap(file, max_upload_bytes)
        data = await pipeline_service.submit_conversion(
            file_bytes=file_bytes,
            filename=file.filename or "",
            content_type=file.content_type,
            do_ocr=do_ocr,
            force_ocr=force_ocr,
            enable_vlm=enable_vlm,
        )
        return SuccessResponse(data=data)
    except ParameterException as e:
        return ParameterResponse(message=str(e.message))
    except DataAlreadyExistsException as e:
        return DataAlreadyExistsResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"转换提交失败: {e}")
        return FailureResponse(message="转换提交失败, 请稍后重试")


@rag_business.get("/convert/status/{job_id}", summary="RAG-查询转换状态")
async def convert_status(
        job_id: str,
        document_service: RagDocumentService = Depends(get_rag_document_service),
):
    """查询指定任务的转换状态。"""
    doc = await document_service.get_document(job_id)
    if not doc:
        return NotFoundResponse(message="任务不存在")
    return SuccessResponse(data=doc)


@rag_business.get("/documents/{job_id}/markdown", summary="RAG-获取文档 Markdown 全文")
async def get_document_markdown(
        job_id: str,
        document_service: RagDocumentService = Depends(get_rag_document_service),
):
    """获取指定文档解析产物的 markdown 全文（按需读取产物目录 md 文件）。

    与状态轮询接口分离: 轮询只传状态字段, 避免每次把整份 markdown 传一遍。
    """
    markdown = await document_service.get_document_markdown(job_id)
    if markdown is None:
        return NotFoundResponse(message="文档不存在")
    return SuccessResponse(data={"job_id": job_id, "markdown": markdown})


@rag_business.get("/documents/{job_id}/terminology", summary="RAG-获取文档术语对照表")
async def get_document_terminology(
        job_id: str,
        document_service: RagDocumentService = Depends(get_rag_document_service),
):
    """获取指定文档的术语对照表 markdown 全文（按需读取产物目录 terminology.md）。

    术语提取失败或被跳过时产物不存在, 返回空串。
    """
    terminology = await document_service.get_document_terminology(job_id)
    if terminology is None:
        return NotFoundResponse(message="文档不存在")
    return SuccessResponse(data={"job_id": job_id, "terminology": terminology})


@rag_business.get("/documents/{job_id}/chunks", summary="RAG-获取文档入库分块列表")
async def get_document_chunks(
        job_id: str,
        document_service: RagDocumentService = Depends(get_rag_document_service),
):
    """获取指定文档最终存入向量库的分块列表（含类型: text/image/table/table_row）。"""
    chunks = await document_service.get_document_chunks(job_id)
    if chunks is None:
        return NotFoundResponse(message="文档不存在")
    return SuccessResponse(data={"job_id": job_id, "total": len(chunks), "chunks": chunks})


@rag_business.post("/documents/summary", summary="RAG-更新文档摘要")
async def update_document_summary(
        request: UpdateSummary = Body(),
        document_service: RagDocumentService = Depends(get_rag_document_service),
):
    """更新指定文档的摘要（用户在详情页编辑保存）。"""
    try:
        doc = await document_service.update_document(
            request.job_id,
            {"summary": request.summary, "updated_at": document_service.now_time()},
        )
        if not doc:
            return NotFoundResponse(message="文档不存在")
        return SuccessResponse(data={"job_id": request.job_id, "summary": request.summary})
    except Exception as e:
        LOGGER.error(f"更新摘要失败: {e}")
        return FailureResponse(message="更新摘要失败, 请稍后重试")


@rag_business.post("/files/delete", summary="RAG-删除文档及其全部产物")
async def delete_files(
        job_ids: str = Form("", description="换行分隔的待移除文档 job_id"),
        document_service: RagDocumentService = Depends(get_rag_document_service),
):
    """移除文档条目, 并由服务端清理其源文件留档、解析产物与向量库分块。"""
    try:
        result = await document_service.delete_files_and_docs(job_ids)
        LOGGER.info(f"删除文件: 成功={result['deleted']}, 失败={result['failed']}")
        return SuccessResponse(data=result)
    except Exception as e:
        LOGGER.error(f"删除文件失败: {e}")
        return FailureResponse(message="删除文件失败, 请稍后重试")


@rag_business.post("/convert/retry", summary="RAG-重试失败的转换任务")
async def convert_retry(
        request: RetryConvert = Body(),
        pipeline_service: RagPipelineService = Depends(get_rag_pipeline_service),
):
    """重试失败文档: 重置状态并重新分发 Celery 任务（沿用原解析配置）。"""
    try:
        data = await pipeline_service.retry_document(request.job_id)
        return SuccessResponse(data=data)
    except ParameterException as e:
        return ParameterResponse(message=str(e.message))
    except NotFoundException as e:
        return NotFoundResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"重试失败: {e}")
        return FailureResponse(message="重试失败, 请稍后重试")


@rag_business.post("/convert/update", summary="RAG-增量更新文档（上传新版本）")
async def convert_update(
        job_id: str = Form(..., description="原文档任务ID（保持不变, 复用同一 job_id）"),
        file: UploadFile = File(...),
        pipeline_service: RagPipelineService = Depends(get_rag_pipeline_service),
):
    """增量更新已入库文档: 上传新版本 PDF, 沿用原 job_id/文件名/解析配置重处理。

    - 仅 complete/failed 终态文档可更新; 更新期间旧版本向量持续服务,
      新版本嵌入成功写入后才原子替换（问答不会读到半成品）;
    - 快速通道①: 文件与现版本字节一致 → 返回 unchanged=true, 不重处理;
    - 快速通道②（Worker 内）: 解析产物一致 → 后处理产物整体复用;
    - 更新失败可经 /convert/rollback 一键恢复上一版本。
    """
    try:
        max_upload_bytes = PROJECT_CONFIG.RAG_MAX_UPLOAD_MB * 1024 * 1024
        file_bytes = await read_upload_with_cap(file, max_upload_bytes)
        data = await pipeline_service.submit_update(
            job_id=job_id,
            file_bytes=file_bytes,
            filename=file.filename or "",
            content_type=file.content_type,
        )
        return SuccessResponse(data=data)
    except ParameterException as e:
        return ParameterResponse(message=str(e.message))
    except NotFoundException as e:
        return NotFoundResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"增量更新提交失败: {e}")
        return FailureResponse(message="增量更新提交失败, 请稍后重试")


@rag_business.post("/convert/rollback", summary="RAG-回滚到上一版本")
async def convert_rollback(
        request: RollbackConvert = Body(),
        pipeline_service: RagPipelineService = Depends(get_rag_pipeline_service),
):
    """增量更新失败后, 把文档回滚到上一版本（prev 归档齐备时可用）。

    恢复顺序以问答正确性优先: 先以 prev 的向量产物重写向量库,
    再恢复产物目录与文档字段; 任一步失败保持可再次回滚。
    """
    try:
        data = await pipeline_service.submit_rollback(request.job_id)
        return SuccessResponse(data=data)
    except ParameterException as e:
        return ParameterResponse(message=str(e.message))
    except NotFoundException as e:
        return NotFoundResponse(message=str(e.message))
    except Exception as e:
        LOGGER.error(f"回滚提交失败: {e}")
        return FailureResponse(message="回滚提交失败, 请稍后重试")


# ==================== 流水线管控接口 ====================

@rag_business.get("/pipeline/status", summary="RAG-获取流水线状态")
async def pipeline_status(
        document_service: RagDocumentService = Depends(get_rag_document_service),
):
    """获取文档处理流水线的整体运行状态。"""
    try:
        data = await document_service.get_pipeline_status()
        return SuccessResponse(data=data)
    except Exception as e:
        LOGGER.error(f"获取流水线状态失败: {e}")
        return FailureResponse(message="获取流水线状态失败, 请稍后重试")


@rag_business.post("/pipeline/cancel", summary="RAG-取消所有转换任务")
async def pipeline_cancel(
        force: bool = False,
        document_service: RagDocumentService = Depends(get_rag_document_service),
):
    """取消所有处理中的转换任务, 立即将文档标记为失败。

    - 软取消（默认）: Worker 在下一个取消检查点停止——docling 单子文档转换
      不可打断, 大文档可能需等当前子文档解析结束;
    - ``?force=true``: 额外以 revoke(terminate=True) 杀掉运行中的 worker 子进程,
      立即生效。task_acks_late 下消息会重回队列, 但文档已被标记取消,
      重投递的任务检测到 cancel_requested 后立即退出, 不会二次执行。
    """
    try:
        result = await document_service.cancel_all_tasks(force=force)
        return SuccessResponse(data=result)
    except Exception as e:
        LOGGER.error(f"取消失败: {e}")
        return FailureResponse(message="取消失败, 请稍后重试")


# ==================== RAG 问答接口 ====================

def _build_query_param(
        request: QuerySelect,
        stream: bool,
        history: List[Dict[str, str]],
        summary: str = "",
        recall: str = "",
):
    """由接口请求构建查询引擎参数。"""
    from applications.jiayueyang.rag.query import QueryParam

    return QueryParam(
        mode=request.mode,
        response_type=request.response_type,
        stream=stream,
        chunk_top_k=request.chunk_top_k or PROJECT_CONFIG.CHUNK_TOP_K,
        rrf_top_k=request.rrf_top_k or PROJECT_CONFIG.RRF_TOP_K,
        dense_top_k=request.dense_top_k,
        bm25_top_k=request.bm25_top_k,
        max_total_tokens=request.max_total_tokens or PROJECT_CONFIG.MAX_TOTAL_TOKENS,
        conversation_history=history,
        conversation_summary=summary,
        conversation_recall=recall,
        user_prompt=request.user_prompt,
        enable_rerank=request.enable_rerank,
        temperature=request.temperature,
        model=request.model,
    )


def _usable_history_messages(msgs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """过滤可注入 LLM 的历史消息: 未完成（generating/interrupted）的回答不入上下文。"""
    return [
        m for m in msgs
        if m.get("role") == "user" or m.get("status", MSG_DONE) == MSG_DONE
    ]


def _sse(event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """构造 sse_starlette 的事件字典。"""
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


@dataclass
class _TurnContext:
    """一次问答的前置准备结果。"""
    history: List[Dict[str, str]] = field(default_factory=list)
    summary: str = ""
    recall: str = ""
    user_index: Optional[int] = None
    assistant_index: Optional[int] = None
    error: Optional[str] = None


async def _memory_context(
        conv_id: int,
        conversation_service: ConversationService,
        cap_index: Optional[int] = None,
        allow_fold: bool = True,
        query: Optional[str] = None,
) -> tuple:
    """加载会话记忆, 返回 (滚动摘要, 近期窗口历史, L4 召回上下文)。

    按摘要边界把消息切分为"窗口（近期, 注入用）+ 溢出（被挤出, 待摘要）";
    allow_fold 且溢出达到批量阈值时同步折叠进滚动摘要（读时兜底, 保证
    "摘要 + 窗口"无缝覆盖、不丢消息）。常规路径下后台任务已在上一轮终态
    预折叠, 此处多为廉价的空检查。

    若提供 query, 额外做 L4 向量回忆: 召回与当前问题相关、且不在近期窗口内
    （seq <= 窗口起点前一1）的旧轮次, 拼成召回上下文。

    :param cap_index: 仅取该下标之前的消息（重新生成场景用, 不含本轮）
    :param allow_fold: 是否允许本次调用触发折叠（重新生成只读, 置 False）
    :param query: 当前问题; 提供时触发 L4 召回（后台预折叠场景置 None）
    """
    summary, up_to_seq = await conversation_service.get_memory_meta(conv_id)
    msgs = await conversation_service.get_messages(conv_id)
    if cap_index is not None:
        msgs = msgs[:cap_index]
    window, overflow, new_up_to = compute_window_and_overflow(
        msgs,
        up_to_seq,
        max_tokens=int(PROJECT_CONFIG.CHAT_HISTORY_MAX_TOKENS or 0),
        max_messages=int(PROJECT_CONFIG.CHAT_HISTORY_MAX_MESSAGES or 0),
    )
    if allow_fold:
        usable_overflow = _usable_history_messages(overflow)
        if len(usable_overflow) >= int(PROJECT_CONFIG.CHAT_SUMMARY_BATCH_MESSAGES or 1):
            folded = await llm_fold_summary(
                summary, usable_overflow, int(PROJECT_CONFIG.CHAT_SUMMARY_MAX_TOKENS or 0),
            )
            if folded is not None:
                await conversation_service.save_memory_meta(conv_id, folded, new_up_to)
                summary = folded
    history = _usable_history_messages(window)
    # L4 向量回忆: 仅在有历史可召回（new_up_to >= 0）且提供了 query 时触发
    recall = ""
    if query and new_up_to >= 0:
        recall = await recall_turn_memory(conv_id, query, new_up_to)
    return summary, history, recall


async def _post_turn_memory(
        conv_id: int,
        conversation_service: ConversationService,
        assistant_index: Optional[int] = None,
) -> None:
    """本轮终态后的后台记忆维护:
    1) 把刚完成的这一轮（用户问题 + 回答）嵌入写入 L4 向量记忆;
    2) 预折叠滚动摘要, 为下一轮提前备好, 使下一轮读时兜底多为廉价空检查。
    异常吞掉（不影响主流程, 读时兜底仍保证正确）。"""
    try:
        # 1) 轮次入库（L4）: 取本轮的 user(assistant_index-1) + assistant 消息
        if assistant_index is not None and assistant_index >= 1:
            msgs = await conversation_service.get_messages(conv_id)
            if assistant_index < len(msgs):
                user_msg = msgs[assistant_index - 1]
                asst_msg = msgs[assistant_index]
                if user_msg.get("role") == "user" and asst_msg.get("role") == "assistant":
                    await upsert_turn_memory(
                        conv_id, assistant_index,
                        user_msg.get("content", ""), asst_msg.get("content", ""),
                    )
        # 2) 预折叠滚动摘要
        await _memory_context(conv_id, conversation_service)
    except Exception as e:
        LOGGER.warning(f"后台记忆维护失败（不影响）: {e}")


async def _prepare_turn(
        request: QuerySelect,
        conversation_service: ConversationService,
) -> _TurnContext:
    """解析历史并完成提问落盘（提问即持久化, 不再等整轮生成结束）。

    - 普通提问: 先读取记忆（滚动摘要 + 近期窗口, 此时本轮尚未写入）, 再追加
      用户消息 + generating 占位回答, 返回两条消息下标供后续增量回写;
    - 重新生成（replace_message_index）: 复用既有回答槽位, 不追加新消息;
    - 未指定会话: 不做持久化, 历史取自请求体（兼容旧调用）。
    """
    if not request.conversation_id:
        return _TurnContext(history=list(request.conversation_history))

    conv_id = request.conversation_id

    if request.replace_message_index is not None:
        idx = request.replace_message_index
        msgs = await conversation_service.get_messages(conv_id)
        if idx >= len(msgs) or msgs[idx].get("role") != "assistant":
            return _TurnContext(error="要重新生成的回答不存在")
        summary, history, _recall = await _memory_context(
            conv_id, conversation_service, cap_index=idx - 1, allow_fold=False,
        )
        if not await conversation_service.reset_message_for_regenerate(conv_id, idx):
            return _TurnContext(error="要重新生成的回答不存在")
        return _TurnContext(
            history=history, summary=summary, user_index=idx - 1, assistant_index=idx,
        )

    summary, history, recall = await _memory_context(
        conv_id, conversation_service, query=request.query,
    )
    indices = await conversation_service.start_qa_round(conv_id, request.query)
    if indices is None:
        # 会话不存在（可能刚被删除）: 降级为不持久化, 不阻塞问答
        return _TurnContext(history=history, summary=summary, recall=recall)
    user_index, assistant_index = indices
    return _TurnContext(
        history=history, summary=summary, recall=recall,
        user_index=user_index, assistant_index=assistant_index,
    )


def _build_retrieval_detail(raw_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """从 raw_data 中提取可持久化的完整检索轨迹。

    保留旧字段，同时补充查询快照和分块溯源字段，兼容历史检索详情。
    """
    if not raw_data:
        return None
    meta = raw_data.get("metadata", {})
    data = raw_data.get("data", {})
    chunks = data.get("chunks", [])
    return {
        "original_query": meta.get("original_query"),
        "resolved_query": meta.get("resolved_query"),
        "rewritten_query": meta.get("rewritten_query") or None,
        "english_query": meta.get("english_query", ""),
        "sub_queries": meta.get("sub_queries") or [],
        "subquery_status": meta.get("subquery_status", "single"),
        "subquery_method": meta.get("subquery_method", "none"),
        "subquery_failure_reason": meta.get("subquery_failure_reason"),
        "subquery_retry_count": meta.get("subquery_retry_count", 0),
        "subquery_coverage": meta.get("subquery_coverage") or {},
        "subquery_evidence": meta.get("subquery_evidence") or {},
        "per_query_candidate_counts": meta.get("per_query_candidate_counts") or {},
        "per_query_candidates": meta.get("per_query_candidates") or {},
        "quota_backfill_count": meta.get("quota_backfill_count", 0),
        "query_mode": meta.get("query_mode", "naive"),
        "matched_mapping_ids": meta.get("matched_mapping_ids") or [],
        "matched_mapping_source": meta.get("matched_mapping_source") or [],
        "mapping_field_match_types": meta.get("mapping_field_match_types") or [],
        "mapping_field_keys": meta.get("mapping_field_keys") or [],
        "mapping_status": meta.get("mapping_status", "unmatched"),
        "mapping_conflicts": meta.get("mapping_conflicts") or [],
        "retrieval_route": meta.get("retrieval_route"),
        "matched_feedback_ids": meta.get("matched_feedback_ids") or [],
        "feedback_scores": meta.get("feedback_scores") or {},
        "scope_doc_ids": meta.get("scope_doc_ids") or [],
        "guidance_scope_doc_ids": meta.get("guidance_scope_doc_ids") or [],
        "guidance_shadow_mode": bool(meta.get("guidance_shadow_mode", False)),
        "scoped_search_enabled": bool(meta.get("scoped_search_enabled", False)),
        "fallback_reason": meta.get("fallback_reason"),
        "answer_truncated": bool(meta.get("answer_truncated", False)),
        "answer_retry_count": meta.get("answer_retry_count", 0),
        "answer_finish_reason": meta.get("answer_finish_reason", "stop"),
        "answer_fallback": meta.get("answer_fallback"),
        "total_found": meta.get("total_chunks_found", 0),
        "final_count": meta.get("final_chunks_count", 0),
        "chunks": [
            {
                "id": c.get("id", ""),
                "doc_id": c.get("doc_id", ""),
                "file_path": c.get("file_path", ""),
                "content": c.get("content", ""),
                "full_content": c.get("content", ""),
                "content_sha256": hashlib.sha256(
                    (c.get("content", "") or "").encode("utf-8")
                ).hexdigest(),
                # score 保持"召回/融合分"语义（RRF 或 BM25）; 开启重排时
                # rerank_score 非空, 前端以它为准展示（分块顺序已是重排序,
                # 列表下标即重排排名）
                "score": c.get("_rrf_score") or c.get("score", 0),
                "raw_score": c.get("score", 0),
                "rrf_score": c.get("_rrf_score"),
                "rerank_score": c.get("rerank_score"),
                "source": c.get("source", "dense"),
                "source_channel": c.get("source", "dense"),
                "modality": c.get("modality", "text"),
                "file_name": c.get("file_name", ""),
                "file_sha256": c.get("file_sha256", ""),
                "reference_id": c.get("reference_id", ""),
                "quota_backfill": bool(c.get("quota_backfill", False)),
                "backfill_query_id": c.get("backfill_query_id"),
                "backfill_reason": c.get("backfill_reason"),
                "passed_global_threshold": c.get("passed_global_threshold"),
                "passed_backfill_guard": c.get("passed_backfill_guard"),
                "matched_query_ids": c.get("_matched_query_ids") or [],
                "order": c.get("order", c.get("chunk_order_index", 0)),
                "chunk_order_index": c.get("chunk_order_index", c.get("order", 0)),
            }
            for c in chunks
        ],
    }


# 生成中回写会话存储的节流间隔（秒）: 刷新/切换会话后能看到增量内容,
# 又不至于每个 token 都向 MySQL 写一次消息行（rag_conversation_message）
_FLUSH_INTERVAL = 1.0


@dataclass
class _StreamJob:
    """一次流式问答的事件总线。

    生成任务与 HTTP 连接解耦: 客户端断连（刷新页面 / 切换会话）只是
    中继端退出, 后台任务继续生成并把结果落盘。SSE 端点通过 subscribe()
    订阅事件; 晚到的订阅者可从 replay 拿到此前已产生的全部事件。
    """
    replay: List[Dict[str, Any]] = field(default_factory=list)
    subscribers: List[asyncio.Queue] = field(default_factory=list)
    finished: bool = False

    def publish(self, event: Dict[str, Any]) -> None:
        self.replay.append(event)
        for q in self.subscribers:
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for ev in self.replay:
            q.put_nowait(ev)
        if self.finished:
            q.put_nowait(None)
        else:
            self.subscribers.append(q)
        return q

    def close(self) -> None:
        self.finished = True
        for q in self.subscribers:
            q.put_nowait(None)
        self.subscribers.clear()


# 在途生成任务引用集: 防止 asyncio.Task 被 GC 提前回收（create_task 仅弱引用）
_RUNNING_JOBS: set = set()

# 活动生成任务登记表: (会话id, 回答消息下标) -> 事件总线。
# 客户端断连（刷新/切换会话）后, 重连接口据此找回仍在运行的任务并续订事件,
# 无需重新提问; 任务结束即注销。
_ACTIVE_JOBS: Dict[Tuple[int, int], "_StreamJob"] = {}


def _deactivate_job(key: Tuple[int, int], job: "_StreamJob") -> None:
    """任务结束后从登记表移除（仅当条目仍指向该 job, 避免误删新一轮任务）。"""
    if _ACTIVE_JOBS.get(key) is job:
        _ACTIVE_JOBS.pop(key, None)


async def _run_stream_job(
        job: _StreamJob,
        request: QuerySelect,
        param,
        assistant_index: Optional[int],
        conversation_service: Optional[ConversationService] = None,
) -> None:
    """后台执行一次流式生成: 检索 → 流式产出 → 增量落盘 → 终态落盘。

    客户端断连不影响本任务; 会话被删除 / 用户点了"停止"时提前收尾。
    """
    from applications.jiayueyang.rag.query import _partial_answer_with_notice, run_query

    conv_id = request.conversation_id
    parts: List[str] = []
    # 思考耗时: 从进入生成（检索+LLM）到首个正文片段的时间（毫秒）
    t0 = time.monotonic()
    thinking_ms: Optional[int] = None

    async def persist(content_status: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> bool:
        """回写当前累计内容（及可选的终态/附加字段）。返回 False 表示会话已不可写。"""
        if conv_id is None or assistant_index is None:
            return True
        return await update_message(
            conv_id, assistant_index, content="".join(parts), status=content_status, extra=extra,
        )

    try:
        try:
            result = await run_query(request.query, param)
        except Exception as e:
            LOGGER.error(f"流式查询失败: {e}")
            if conv_id is not None and assistant_index is not None:
                await update_message(conv_id, assistant_index, status=MSG_INTERRUPTED)
            job.publish(_sse("error", {"type": "error", "content": "查询失败, 请稍后重试"}))
            return

        # 1. 检索详情 — 无条件发送
        retrieval = _build_retrieval_detail(result.raw_data) if result.raw_data else None
        job.publish(_sse("retrieval", {
            "type": "retrieval",
            "rewritten_query": (retrieval or {}).get("rewritten_query") or None,
            "query_mode": (retrieval or {}).get("query_mode", "?"),
            "total_found": (retrieval or {}).get("total_found", 0),
            "final_count": (retrieval or {}).get("final_count", 0),
            "chunks": (retrieval or {}).get("chunks", []),
        }))

        # 2. 参考文献列表
        if request.include_references and result.raw_data:
            refs = result.raw_data.get("data", {}).get("references", [])
            job.publish(_sse("references", {"type": "references", "references": refs}))

        # 3. 内容（流式或非流式）, 边产出边节流落盘
        last_flush = time.monotonic()
        try:
            if result.is_streaming and result.response_iterator:
                async for chunk in result.response_iterator:
                    if not chunk:
                        continue
                    parts.append(chunk)
                    if thinking_ms is None:
                        thinking_ms = int((time.monotonic() - t0) * 1000)
                    job.publish(_sse("content", {"type": "content", "content": chunk}))
                    # 首个 chunk 立即落盘（此后刷新/轮询即可见内容）, 之后按节流间隔回写
                    if len(parts) == 1 or time.monotonic() - last_flush >= _FLUSH_INTERVAL:
                        last_flush = time.monotonic()
                        if not await persist():
                            return  # 会话已被删除, 停止生成
                        # 用户点了"停止": 存储侧已置 interrupted, 任务就此收尾
                        if await read_message_status(conv_id, assistant_index) == MSG_INTERRUPTED:
                            job.publish(_sse("error", {"type": "error", "content": "已停止生成"}))
                            return
            elif result.content:
                parts.append(result.content)
                thinking_ms = int((time.monotonic() - t0) * 1000)
                job.publish(_sse("content", {"type": "content", "content": result.content}))
        except Exception as e:
            LOGGER.error(f"生成中断: {e}")
            await persist(MSG_INTERRUPTED)
            job.publish(_sse("error", {"type": "error", "content": "生成中断, 请重试"}))
            return

        # 流式接口无法像非流式那样重生成，但保留供应商 finish_reason，
        # 让前端和检索详情明确知道答案是正常结束还是达到长度上限。
        stream_status = getattr(result.response_iterator, "finish_reason", None)
        stream_truncated = stream_status == "length"
        if stream_truncated:
            # 流式调用无法像非流式调用一样复用证据重生成；将明确提示追加到
            # 已输出内容并落盘，让前端和历史消息都能看到截断原因及处理建议。
            notice = _partial_answer_with_notice("")
            parts.append(notice)
            job.publish(_sse("content", {"type": "content", "content": f"\n\n{notice}"}))
        if retrieval is not None:
            retrieval["answer_truncated"] = stream_truncated
            retrieval["answer_finish_reason"] = stream_status or "stop"
            retrieval["answer_retry_count"] = 0
            retrieval["answer_fallback"] = "stream_partial" if stream_truncated else None

        # 4. 终态落盘 + 完成事件（用户抢在收尾前点了"停止"时不覆盖 interrupted）
        #    思考耗时随消息持久化; 检索详情写入独立表, 历史回看均可见
        if (
            conv_id is None
            or assistant_index is None
            or await read_message_status(conv_id, assistant_index) != MSG_INTERRUPTED
        ):
            await persist(
                MSG_TRUNCATED if stream_truncated else MSG_DONE,
                extra={"thinking_ms": thinking_ms},
            )
            if conv_id is not None and assistant_index is not None and retrieval is not None:
                await save_retrieval_detail(conv_id, assistant_index, retrieval)
        # done 事件附带思考耗时: 刷新/切换后重连的客户端靠 replay 重建消息,
        # 拿不到本地测量值, 以服务端落盘的 thinking_ms 为准展示
        job.publish(_sse("done", {
            "type": "done",
            "status": MSG_TRUNCATED if stream_truncated else MSG_DONE,
            "thinking_ms": thinking_ms,
            "truncated": stream_truncated,
            "finish_reason": stream_status or "stop",
        }))
    finally:
        job.close()
        # 本轮终态后后台记忆维护（轮次入 L4 向量库 + 预折叠摘要, 不阻塞响应）
        if conv_id is not None and conversation_service is not None:
            asyncio.create_task(_post_turn_memory(conv_id, conversation_service, assistant_index))


async def _persist_nonstream_result(
        conv_id: int,
        assistant_index: int,
        task: "asyncio.Task",
) -> None:
    """非流式请求被客户端中断后的兜底落盘: 任务完成时把结果写回会话。

    以协程实现（数据库写入为异步）, 由任务完成回调经 ensure_future
    调度到当前事件循环执行。
    """
    try:
        result = task.result()
        # 用户可能已手动停止（interrupted）, 完成的结果不再覆盖中断状态
        if await read_message_status(conv_id, assistant_index) != MSG_INTERRUPTED:
            await update_message(conv_id, assistant_index, content=result.content or "未能生成回答。", status=MSG_DONE)
    except Exception as e:
        LOGGER.error(f"非流式查询失败（延迟落盘）: {e}")
        await update_message(conv_id, assistant_index, status=MSG_INTERRUPTED)


@rag_business.post("/query", summary="RAG-问答（非流式）")
async def query(
        request: QuerySelect = Body(),
        conversation_service: ConversationService = Depends(get_conversation_service),
):
    """非流式 RAG 问答接口。提问即持久化; 客户端中途刷新也不会丢消息。"""
    prepared: Optional[_TurnContext] = None
    try:
        from applications.jiayueyang.rag.query import run_query

        prepared = await _prepare_turn(request, conversation_service)
        if prepared.error:
            return FailureResponse(message=prepared.error)
        param = _build_query_param(
            request, stream=False, history=prepared.history,
            summary=prepared.summary, recall=prepared.recall,
        )

        # shield: 客户端断连只中断等待, 生成任务继续跑完并落盘
        t0 = time.monotonic()
        task = asyncio.create_task(run_query(request.query, param))
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            if (
                prepared is not None
                and request.conversation_id is not None
                and prepared.assistant_index is not None
            ):
                # 兜底落盘为协程（异步 DB 写入）, done 回调内经 ensure_future 调度
                task.add_done_callback(
                    lambda t: asyncio.ensure_future(
                        _persist_nonstream_result(request.conversation_id, prepared.assistant_index, t)
                    )
                )
            raise

        references: Optional[list] = None
        retrieval: Optional[dict] = None
        if result.raw_data:
            references = result.raw_data.get("data", {}).get("references", []) if request.include_references else None
            retrieval = _build_retrieval_detail(result.raw_data)

        data = {
            "response": result.content or "未能生成回答。",
            "references": references,
            "retrieval": retrieval,
            # 本轮消息下标（供前端"重新生成"定位服务端消息; 未持久化时为 None）
            "user_message_index": prepared.user_index,
            "message_index": prepared.assistant_index,
        }

        # 终态落盘（占位消息在 _prepare_turn 已写入）, 附带思考耗时;
        # 检索详情写入独立的检索详情表, 不进消息表
        if request.conversation_id is not None and prepared.assistant_index is not None:
            await update_message(
                request.conversation_id, prepared.assistant_index,
                content=data["response"], status=MSG_DONE,
                extra={"thinking_ms": int((time.monotonic() - t0) * 1000)},
            )
            if retrieval is not None:
                await save_retrieval_detail(request.conversation_id, prepared.assistant_index, retrieval)

        # 本轮终态后后台记忆维护（轮次入 L4 向量库 + 预折叠摘要, 不阻塞响应）
        if request.conversation_id is not None:
            asyncio.create_task(_post_turn_memory(
                request.conversation_id, conversation_service, prepared.assistant_index,
            ))

        return SuccessResponse(data=data)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        LOGGER.error(f"查询失败: {e}")
        if (
            prepared is not None
            and request.conversation_id is not None
            and prepared.assistant_index is not None
        ):
            await update_message(request.conversation_id, prepared.assistant_index, status=MSG_INTERRUPTED)
        return FailureResponse(message="查询失败, 请稍后重试")


@rag_business.post("/query/stream", summary="RAG-问答（流式 SSE）")
async def query_stream(
        request: QuerySelect = Body(),
        conversation_service: ConversationService = Depends(get_conversation_service),
):
    """流式 RAG 问答接口（Server-Sent Events）。

    提问即持久化: 用户消息与 generating 占位回答在生成开始前就已写入会话,
    刷新页面 / 切换会话不会丢消息; 生成任务独立于 HTTP 连接, 断连后继续
    生成并增量落盘, 重新打开会话可通过 /query/stream/resume 重连接回
    在途任务（无活动任务时回退读取持久化数据）。

    事件序列: persisted（可选, 消息下标）→ retrieval → references（可选）
    → content... → done; 失败/停止时为 error。
    """
    prepared = await _prepare_turn(request, conversation_service)
    if prepared.error:
        async def prepare_error_generator():
            yield _sse("error", {"type": "error", "content": prepared.error})

        return EventSourceResponse(prepare_error_generator())

    param = _build_query_param(
        request, stream=True, history=prepared.history,
        summary=prepared.summary, recall=prepared.recall,
    )
    job = _StreamJob()
    task = asyncio.create_task(
        _run_stream_job(job, request, param, prepared.assistant_index, conversation_service)
    )
    _RUNNING_JOBS.add(task)
    task.add_done_callback(_RUNNING_JOBS.discard)
    # 登记活动任务: 客户端断连后可按 (会话, 消息下标) 重连接回本任务
    if request.conversation_id is not None and prepared.assistant_index is not None:
        job_key = (request.conversation_id, prepared.assistant_index)
        _ACTIVE_JOBS[job_key] = job
        task.add_done_callback(lambda _t, _key=job_key, _job=job: _deactivate_job(_key, _job))

    async def relay_generator():
        # 先告知前端本轮消息在服务端的下标（重新生成等功能据此定位）
        if prepared.user_index is not None and prepared.assistant_index is not None:
            yield _sse("persisted", {
                "type": "persisted",
                "user_index": prepared.user_index,
                "assistant_index": prepared.assistant_index,
            })
        queue = job.subscribe()
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

    return EventSourceResponse(relay_generator())


@rag_business.get("/query/stream/resume", summary="RAG-重连在途流式生成（SSE）")
async def query_stream_resume(conversation_id: int, index: int):
    """刷新页面 / 切换会话后, 重连该会话中仍在运行的生成任务。

    按 (会话id, 回答消息下标) 查找活动任务:
    - 命中: 订阅并中继本轮自开始以来的全部事件（replay + 实时）,
      前端据此从零重建该消息内容; **不触发任何新的检索/生成**;
    - 未命中（任务已结束或进程重启过）: 立即返回 no_active_stream 事件,
      前端回退读取已持久化的消息数据。
    """
    job = _ACTIVE_JOBS.get((conversation_id, index))

    async def relay_generator():
        if job is None:
            yield _sse("no_active_stream", {"type": "no_active_stream"})
            return
        queue = job.subscribe()
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

    return EventSourceResponse(relay_generator())


# ==================== 模型信息接口 ====================

@rag_business.get("/models", summary="RAG-获取模型信息")
async def query_models():
    """获取当前配置的 LLM 模型信息与向量库统计。"""
    try:
        from applications.jiayueyang.rag.milvus_store import get_collection_stats
        # 同步 Milvus 调用移交线程池, 避免阻塞 Web 事件循环
        stats = await asyncio.to_thread(get_collection_stats)
        data = {"model": PROJECT_CONFIG.LLM_MODEL, "vector_store": stats}
        return SuccessResponse(data=data)
    except Exception as e:
        LOGGER.error(f"获取模型信息失败: {e}")
        return FailureResponse(message="获取模型信息失败, 请稍后重试")
