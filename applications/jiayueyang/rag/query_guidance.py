"""采纳经验查询指导。

经验只决定“先搜哪些文档”，不直接复用历史答案。MySQL 中的反馈快照是
权威状态，Milvus 的 rag_query_memory 只负责相似度召回；两者联合校验后才
返回可用于限定检索范围的文档 ID。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from configure import LOGGER, PROJECT_CONFIG
from applications.jiayueyang.models.feedback_model import RagAnswerFeedback
from applications.jiayueyang.rag.embedding import embed_texts
from applications.jiayueyang.rag.milvus_store import search_query_memory


def _score(hit: Dict[str, Any]) -> float:
    try:
        return float(hit.get("distance") or 0.0)
    except (TypeError, ValueError):
        return 0.0


async def recall_query_guidance(
    query: str,
    *,
    scope: Optional[str] = None,
) -> Dict[str, Any]:
    """召回相似采纳经验并解析其文档范围。

    返回字段：``matched_feedback_ids``、``feedback_scores``、
    ``scope_doc_ids``、``matched``。任意依赖不可用时返回空指导，调用方
    继续全库检索，保证经验服务故障不阻断问答。
    """
    empty = {
        "matched": False,
        "matched_feedback_ids": [],
        "feedback_scores": {},
        "scope_doc_ids": [],
        "fallback_reason": None,
    }
    if not PROJECT_CONFIG.QUERY_MEMORY_ENABLED or not (query or "").strip():
        return empty
    try:
        vectors = await embed_texts([query.strip()], quick=True)
        hits = await asyncio.to_thread(
            search_query_memory,
            vectors,
            top_k=PROJECT_CONFIG.QUERY_MEMORY_TOP_K,
            source_types=["accepted_feedback"],
            scope=scope,
        )
        hits = [h for h in hits if _score(h) >= PROJECT_CONFIG.QUERY_MEMORY_MIN_SCORE]
        if not hits:
            empty["fallback_reason"] = "query_memory_no_match"
            return empty

        ids = [str(h.get("source_id") or "") for h in hits if h.get("source_id")]
        rows = await RagAnswerFeedback.filter(
            feedback_uid__in=ids,
            action="accepted",
            index_status="synced",
        ).all()
        by_id = {row.feedback_uid: row for row in rows}
        matched_ids: List[str] = []
        scores: Dict[str, float] = {}
        doc_ids: set[str] = set()
        for hit in hits:
            feedback_id = str(hit.get("source_id") or "")
            row = by_id.get(feedback_id)
            if row is None:
                continue
            hit_score = _score(hit)
            if feedback_id not in scores:
                matched_ids.append(feedback_id)
                scores[feedback_id] = hit_score
            elif hit_score > scores[feedback_id]:
                scores[feedback_id] = hit_score
            doc_ids.update(str(item) for item in (row.related_doc_ids or []) if item)

        if not matched_ids or not doc_ids:
            empty["fallback_reason"] = "query_memory_scope_empty"
            return empty
        return {
            "matched": True,
            "matched_feedback_ids": matched_ids,
            "feedback_scores": scores,
            "scope_doc_ids": sorted(doc_ids),
            "fallback_reason": None,
        }
    except Exception as exc:
        LOGGER.warning("查询指导服务不可用，回退全库检索: %s", exc)
        empty["fallback_reason"] = "query_guidance_unavailable"
        return empty


def build_doc_filter(doc_ids: List[str]) -> str:
    """构造 Milvus VARCHAR doc_id 过滤表达式并转义双引号。"""
    values = [str(item).replace("\\", "\\\\").replace('"', '\\"') for item in doc_ids if str(item)]
    if not values:
        return ""
    return "doc_id in [" + ", ".join(f'"{value}"' for value in values) + "]"
