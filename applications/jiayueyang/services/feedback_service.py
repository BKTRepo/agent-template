# -*- coding: utf-8 -*-
"""回答采纳/取消采纳服务。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from tortoise.transactions import in_transaction

from applications.jiayueyang.models.conversation_model import (
    MSG_DONE,
    RagConversationMessage,
    RagConversationRetrieval,
)
from applications.jiayueyang.models.feedback_model import RagAnswerFeedback
from applications.jiayueyang.services.mapping_evidence_service import query_fingerprint
from core.exceptions import NotFoundException, ParameterException
from configure import LOGGER


class FeedbackService:
    """从服务端消息和检索详情生成独立反馈快照。"""

    @staticmethod
    def _mapping_snapshot(retrieval: Dict[str, Any]) -> List[Dict[str, Any]]:
        meta = retrieval.get("metadata", retrieval)
        ids = meta.get("matched_mapping_ids") or []
        sources = meta.get("matched_mapping_source") or []
        return [
            {"mapping_id": mapping_id, "mapping_source": sources[index] if index < len(sources) else None}
            for index, mapping_id in enumerate(ids)
            if mapping_id
        ]

    @staticmethod
    def _related_ids(retrieval: Dict[str, Any]) -> tuple[List[str], List[str]]:
        meta = retrieval.get("metadata", retrieval)
        chunks = retrieval.get("chunks") or retrieval.get("data", {}).get("chunks", [])
        doc_ids = set(meta.get("scope_doc_ids") or [])
        chunk_ids: List[str] = []
        for chunk in chunks:
            if chunk.get("doc_id"):
                doc_ids.add(str(chunk["doc_id"]))
            if chunk.get("id"):
                chunk_ids.append(str(chunk["id"]))
        return sorted(doc_ids), chunk_ids

    @staticmethod
    async def _dispatch_after_response(task: Any, args: tuple[Any, ...], label: str) -> None:
        """异步投递反馈任务，不让 Redis/Celery 故障阻塞采纳接口。"""
        try:
            await asyncio.to_thread(
                task.apply_async,
                args=args,
                retry=False,
            )
        except Exception as exc:
            # 反馈行已经提交，Beat 会根据 pending/failed 状态再次补偿。
            LOGGER.warning("反馈异步任务投递失败，将由巡检补偿: %s, %s", label, exc)

    async def get_feedback(self, conversation_id: int, message_seq: int) -> Optional[Dict[str, Any]]:
        row = await RagAnswerFeedback.filter(
            conversation_id=conversation_id,
            assistant_message_seq=message_seq,
        ).first()
        if row is None:
            return None
        return {
            "feedback_uid": row.feedback_uid,
            "conversation_id": row.conversation_id,
            "message_seq": row.assistant_message_seq,
            "action": row.action,
            "effective": row.action == "accepted" and row.index_status != "deleted",
            "index_status": row.index_status,
            "updated_time": row.updated_time,
        }

    async def set_feedback(
        self,
        conversation_id: int,
        message_seq: int,
        action: str,
        operator: Optional[str] = None,
    ) -> Dict[str, Any]:
        if action not in {"accepted", "revoked"}:
            raise ParameterException(message="action 只能是 accepted 或 revoked")

        dispatch_action: Optional[str] = None
        dispatch_uid: Optional[str] = None
        async with in_transaction() as connection:
            message = await RagConversationMessage.filter(
                conversation_id=conversation_id, seq=message_seq,
            ).using_db(connection).first()
            if message is None:
                raise NotFoundException(message="回答消息不存在")
            if message.role != "assistant":
                raise ParameterException(message="只有 assistant 回答可以采纳")
            if action == "accepted" and message.status != MSG_DONE:
                raise ParameterException(message="回答尚未完成，不能采纳")

            existing = await RagAnswerFeedback.filter(
                conversation_id=conversation_id,
                assistant_message_seq=message_seq,
            ).using_db(connection).select_for_update().first()

            if action == "revoked":
                if existing is None:
                    raise NotFoundException(message="该回答尚未采纳")
                existing.action = "revoked"
                # 先标记为待删除；Milvus 删除失败时由 Beat 按此状态补偿，
                # 删除成功后同步服务再改为 deleted。
                existing.index_status = "delete_pending"
                existing.mapping_extract_status = "revoke_pending"
                existing.mapping_extract_error = None
                existing.operator = operator
                await existing.save(using_db=connection)
                row = existing
                dispatch_action = "revoked"
                dispatch_uid = row.feedback_uid
            else:
                user_message = await RagConversationMessage.filter(
                    conversation_id=conversation_id,
                    seq__lt=message_seq,
                    role="user",
                ).using_db(connection).order_by("-seq").first()
                retrieval_row = await RagConversationRetrieval.filter(
                    conversation_id=conversation_id,
                    message_seq=message_seq,
                ).using_db(connection).first()
                retrieval = retrieval_row.detail if retrieval_row else {}
                metadata = retrieval.get("metadata", retrieval)
                related_doc_ids, related_chunk_ids = self._related_ids(retrieval)
                snapshot = {
                    "message_seq": message.seq,
                    "role": message.role,
                    "status": message.status,
                    "content": message.content or "",
                    "thinking_ms": message.thinking_ms,
                    "created_time": message.created_time.isoformat() if message.created_time else None,
                }
                values = {
                    "action": "accepted",
                    "original_query": user_message.content if user_message else metadata.get("original_query"),
                    "resolved_query": metadata.get("resolved_query"),
                    "rewritten_query": metadata.get("rewritten_query"),
                    "english_query": metadata.get("english_query"),
                    "sub_queries": metadata.get("sub_queries") or [],
                    "answer_snapshot": snapshot,
                    "retrieval_snapshot": retrieval,
                    "related_doc_ids": related_doc_ids,
                    "related_chunk_ids": related_chunk_ids,
                    "mapping_snapshot": self._mapping_snapshot(retrieval),
                    "scope": (metadata.get("scope") or metadata.get("mapping_scope")),
                    "index_status": "pending",
                    "query_fingerprint": query_fingerprint(
                        metadata.get("resolved_query")
                        or (user_message.content if user_message else metadata.get("original_query"))
                    ),
                    "mapping_extract_status": "pending",
                    "mapping_extract_error": None,
                    "operator": operator,
                }
                if existing is None:
                    row = await RagAnswerFeedback.create(
                        using_db=connection,
                        feedback_uid=f"fb-{uuid4().hex}",
                        conversation_id=conversation_id,
                        assistant_message_seq=message_seq,
                        **values,
                    )
                else:
                    for key, value in values.items():
                        setattr(existing, key, value)
                    await existing.save(using_db=connection)
                    row = existing
                dispatch_action = "accepted"
                dispatch_uid = row.feedback_uid

        # 事务提交后再投递，确保 Worker 读取到已提交的 MySQL 状态。投递放到
        # 后台线程执行，Redis/Celery 暂时不可用时不阻塞用户的采纳响应；Beat
        # 后续会根据 pending/failed 状态补偿。
        if dispatch_action and dispatch_uid:
            from celery_scheduler.tasks.task_query_memory_sync import sync_query_memory_record_task
            from celery_scheduler.tasks.task_mapping_evidence import process_mapping_evidence_task

            asyncio.create_task(self._dispatch_after_response(
                sync_query_memory_record_task,
                ("accepted_feedback", dispatch_uid),
                f"query-memory:{dispatch_uid}",
            ))
            asyncio.create_task(self._dispatch_after_response(
                process_mapping_evidence_task,
                (dispatch_uid,),
                f"mapping-evidence:{dispatch_uid}",
            ))

        return {
            "feedback_uid": row.feedback_uid,
            "conversation_id": conversation_id,
            "message_seq": message_seq,
            "action": row.action,
            "effective": row.action == "accepted",
            "index_status": row.index_status,
            "has_retrieval_snapshot": bool(row.retrieval_snapshot),
        }


feedback_service = FeedbackService()
