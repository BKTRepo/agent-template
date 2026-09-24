# -*- coding: utf-8 -*-
"""MySQL -> Milvus 查询经验同步服务。

MySQL 记录是唯一可信来源，Milvus 只保存可重建索引。同步失败只更新索引状态，
不会回滚用户采纳或修改用户上传的映射原始数据。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List

from applications.jiayueyang.models.feedback_model import RagAnswerFeedback
from applications.jiayueyang.models.term_mapping_model import (
    RagTermMappingLearned,
    RagTermMappingSource,
)
from applications.jiayueyang.rag.embedding import embed_texts
from applications.jiayueyang.rag.milvus_store import (
    delete_query_memory,
    upsert_query_memory,
)
from configure import LOGGER


def _texts(canonical: str, aliases: Iterable[str]) -> List[str]:
    values: List[str] = []
    for value in [canonical, *aliases]:
        value = str(value or "").strip()
        if value and value not in values:
            values.append(value)
    return values


class QueryMemorySyncService:
    """负责单条同步和待处理记录巡检。"""

    async def sync_feedback(self, feedback_uid: str) -> Dict[str, Any]:
        row = await RagAnswerFeedback.filter(feedback_uid=feedback_uid).first()
        if row is None:
            return {"success": False, "status": "missing", "feedback_uid": feedback_uid}

        if row.action != "accepted" or row.index_status in {
            "deleted", "delete_pending", "delete_failed",
        }:
            try:
                deleted = await asyncio.to_thread(
                    delete_query_memory, source_type="accepted_feedback", source_id=row.feedback_uid,
                )
            except Exception as exc:
                row.index_status = "delete_failed"
                await row.save()
                LOGGER.error(f"采纳反馈删除查询经验失败: {feedback_uid}, {type(exc).__name__}: {exc}")
                return {
                    "success": False,
                    "status": "delete_failed",
                    "error": str(exc),
                    "feedback_uid": feedback_uid,
                }
            row.index_status = "deleted"
            await row.save()
            return {"success": deleted >= 0, "status": "deleted", "deleted": deleted, "feedback_uid": feedback_uid}

        query_text = row.original_query or row.rewritten_query or row.english_query or ""
        canonical = row.rewritten_query or row.original_query or row.english_query or ""
        if not query_text.strip():
            row.index_status = "failed"
            await row.save()
            return {"success": False, "status": "failed", "error": "反馈缺少可向量化查询", "feedback_uid": feedback_uid}

        try:
            vectors = await embed_texts(_texts(query_text, [canonical, row.english_query or ""]), quick=True)
            records = []
            for index, text in enumerate(_texts(query_text, [canonical, row.english_query or ""])):
                records.append({
                    "id": f"feedback:{row.feedback_uid}:{index}",
                    "vector": vectors[index],
                    "source_type": "accepted_feedback",
                    "source_id": row.feedback_uid,
                    "query_text": text,
                    "canonical_query": canonical,
                    "scope": row.scope or "",
                })
            written = await asyncio.to_thread(upsert_query_memory, records)
            row.index_status = "synced"
            await row.save()
            return {"success": True, "status": "synced", "written": written, "feedback_uid": feedback_uid}
        except Exception as exc:
            row.index_status = "failed"
            await row.save()
            LOGGER.error(f"采纳反馈同步查询经验失败: {feedback_uid}, {type(exc).__name__}: {exc}")
            return {"success": False, "status": "failed", "error": str(exc), "feedback_uid": feedback_uid}

    async def sync_mapping(self, mapping_id: str, learned: bool = False) -> Dict[str, Any]:
        model = RagTermMappingLearned if learned else RagTermMappingSource
        id_field = "learned_mapping_id" if learned else "mapping_id"
        row = await model.filter(**{id_field: mapping_id}).first()
        source_type = "learned_mapping" if learned else "source_mapping"
        if row is None:
            deleted = await asyncio.to_thread(delete_query_memory, source_type=source_type, source_id=mapping_id)
            return {"success": deleted >= 0, "status": "deleted", "deleted": deleted, "source_id": mapping_id}
        active = row.status == ("active" if learned else "enabled")
        if not active:
            deleted = await asyncio.to_thread(delete_query_memory, source_type=source_type, source_id=mapping_id)
            return {"success": deleted >= 0, "status": "deleted", "deleted": deleted, "source_id": mapping_id}
        values = _texts(row.canonical_zh, list(row.aliases_zh or []) + list(row.aliases_en or []) + ([row.official_en] if row.official_en else []))
        try:
            vectors = await embed_texts(values, quick=True)
            records = [{
                "id": f"{source_type}:{mapping_id}:{index}", "vector": vectors[index],
                "source_type": source_type, "source_id": mapping_id,
                "query_text": text, "canonical_query": row.canonical_zh,
                "scope": row.scope or "",
            } for index, text in enumerate(values)]
            written = await asyncio.to_thread(upsert_query_memory, records)
            return {"success": True, "status": "synced", "written": written, "source_id": mapping_id}
        except Exception as exc:
            LOGGER.error(f"术语映射同步查询经验失败: {mapping_id}, {type(exc).__name__}: {exc}")
            return {"success": False, "status": "failed", "error": str(exc), "source_id": mapping_id}

    async def sync_pending_feedback(self, limit: int = 100) -> Dict[str, Any]:
        rows = await RagAnswerFeedback.filter(
            action__in=["accepted", "revoked"],
            index_status__in=["pending", "failed", "delete_pending", "delete_failed"],
        ).order_by("created_time").limit(max(1, min(int(limit), 500)))
        results = [await self.sync_feedback(row.feedback_uid) for row in rows]
        return {
            "success": all(item.get("success") for item in results) if results else True,
            "processed": len(results),
            "synced": sum(item.get("status") == "synced" for item in results),
            "failed": sum(item.get("status") == "failed" for item in results),
            "deleted": sum(item.get("status") == "deleted" for item in results),
            "delete_failed": sum(item.get("status") == "delete_failed" for item in results),
        }


query_memory_sync_service = QueryMemorySyncService()

