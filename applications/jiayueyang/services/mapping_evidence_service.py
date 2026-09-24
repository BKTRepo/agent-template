# -*- coding: utf-8 -*-
"""从采纳反馈提取、去重并聚合程序术语映射。

一次采纳只产生证据；至少两条独立且语义相近的证据才会创建并自动激活程序映射。
该服务永远不写入用户上传的权威映射表。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import uuid4, uuid5, NAMESPACE_URL

from tortoise.exceptions import IntegrityError

from applications.jiayueyang.models.feedback_model import RagAnswerFeedback
from applications.jiayueyang.models.mapping_evidence_model import RagTermMappingEvidence
from applications.jiayueyang.models.term_mapping_model import (
    RagTermMappingLearned,
    RagTermMappingSource,
)
from applications.jiayueyang.rag.embedding import embed_texts
from applications.jiayueyang.rag.llm import chat_completion
from applications.jiayueyang.services.term_mapping_import_service import normalize_term
from configure import LOGGER, PROJECT_CONFIG


_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\s\.,，。!！?？:：;；、/\\_\-—]+")
_ALGORITHM_VERSION = "mapping-evidence-v1"

# 同一进程内即时任务和 Beat 任务可能同时处理同一个 mapping_key。
# 进程间仍依靠数据库唯一键和下方的冲突重查逻辑兜底。
_mapping_aggregate_locks: Dict[Tuple[int, str], asyncio.Lock] = {}


def normalize_query_for_fingerprint(value: Any) -> str:
    """生成用于判断完全重复问题的稳定文本。"""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = _PUNCT_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def query_fingerprint(value: Any) -> str:
    return hashlib.sha256(normalize_query_for_fingerprint(value).encode("utf-8")).hexdigest()


def mapping_key_for(canonical_zh: str, scope: Optional[str] = None) -> str:
    """Return the stable learned-mapping key.

    ``scope`` is intentionally not part of the key.  The current knowledge
    base is limited to credit-card material, and scope is descriptive
    metadata rather than a hard partition.  The optional argument remains in
    the signature so callers using the previous API keep working.
    """
    del scope
    raw = normalize_term(canonical_zh)
    if len(raw) <= 255:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"{raw[:222]}|{digest}"


def _unique(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        key = normalize_term(text)
        if text and key and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _json_object(text: Any) -> Dict[str, Any]:
    if isinstance(text, dict):
        return text
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(raw[start:end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _chunks_from_feedback(feedback: RagAnswerFeedback) -> Tuple[List[str], List[str]]:
    retrieval = feedback.retrieval_snapshot or {}
    chunks = retrieval.get("chunks") or retrieval.get("data", {}).get("chunks", [])
    docs: List[str] = []
    texts: List[str] = []
    for chunk in chunks[:8]:
        if not isinstance(chunk, dict):
            continue
        if chunk.get("doc_id"):
            docs.append(str(chunk["doc_id"]))
        content = str(chunk.get("content") or "").strip()
        if content:
            texts.append(content[:1800])
    docs.extend(str(item) for item in (feedback.related_doc_ids or []) if item)
    return _unique(docs), texts


def _proposal_aliases(proposal: Dict[str, Any]) -> List[str]:
    values: List[Any] = []
    values.extend(proposal.get("aliases_zh") or [])
    if proposal.get("alias_zh"):
        values.append(proposal["alias_zh"])
    if proposal.get("alias"):
        values.append(proposal["alias"])
    return _unique(values)


def _build_extraction_prompt(feedback: RagAnswerFeedback, evidence_text: str) -> str:
    return f"""你是银行卡技术文档的术语映射抽取器。只从给定证据中提取用户说法到规范术语的映射，不回答问题。

输出 JSON：{{"mappings":[{{"aliases_zh":["用户原话"],"canonical_zh":"中文标准词","official_en":"官方英文词或空字符串","aliases_en":[],"scope":"适用范围或空字符串","confidence":0.0}}]}}

严格要求：
1. aliases_zh 中的每个别名必须原样出现在原始问题中；
2. canonical_zh 必须能在改写查询、英文查询或检索证据中找到；
3. 不确定时返回空 mappings，不要猜测；
4. 不要把已经是标准词的普通重复写法当成新别名；
5. 只输出 JSON。

原始问题：{feedback.original_query or ''}
指代消解问题：{feedback.resolved_query or ''}
中文改写查询：{feedback.rewritten_query or ''}
英文检索查询：{feedback.english_query or ''}
适用范围：{feedback.scope or ''}
检索证据：{evidence_text[:12000]}
"""


async def _extract_proposals(feedback: RagAnswerFeedback) -> List[Dict[str, Any]]:
    docs, chunks = _chunks_from_feedback(feedback)
    evidence_text = "\n\n---\n\n".join(chunks)
    if not evidence_text:
        evidence_text = str(feedback.retrieval_snapshot or {})[:12000]
    try:
        raw = await asyncio.wait_for(
            chat_completion(
                messages=_build_extraction_prompt(feedback, evidence_text),
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=800,
            ),
            timeout=30.0,
        )
    except Exception as exc:
        LOGGER.warning("采纳映射提取调用失败: %s", exc)
        raise

    data = _json_object(raw)
    proposals = data.get("mappings") or []
    if not isinstance(proposals, list):
        return []
    original = normalize_query_for_fingerprint(feedback.original_query or feedback.resolved_query)
    reference = normalize_query_for_fingerprint(
        " ".join([
            feedback.rewritten_query or "",
            feedback.english_query or "",
            evidence_text,
            json.dumps(getattr(feedback, "mapping_snapshot", None) or [], ensure_ascii=False),
        ])
    )
    result: List[Dict[str, Any]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        canonical = str(proposal.get("canonical_zh") or "").strip()
        aliases = [alias for alias in _proposal_aliases(proposal) if normalize_term(alias) in original]
        if not canonical or not aliases:
            continue
        if normalize_term(canonical) not in reference:
            continue
        scope = str(proposal.get("scope") or feedback.scope or "").strip() or None
        aliases_en = _unique(proposal.get("aliases_en") or [])
        official_en = str(proposal.get("official_en") or "").strip() or None
        # 英文词若由模型返回，必须能在查询改写、既有映射快照或检索证据中核验；
        # 无法核验时按“未填写”处理，避免把模型猜测写入程序映射。
        if official_en and normalize_term(official_en) not in normalize_term(reference):
            official_en = None
        confidence = float(proposal.get("confidence") or 0.0)
        confidence = min(0.99, max(0.0, confidence))
        normalized_keys = _unique([canonical, *aliases, official_en or "", *aliases_en])
        result.append({
            "canonical_zh": canonical,
            "aliases_zh": aliases,
            "official_en": official_en,
            "aliases_en": aliases_en,
            "scope": scope,
            "normalized_keys": normalized_keys,
            "mapping_key": mapping_key_for(canonical),
            "supporting_doc_ids": docs,
            "supporting_chunk_ids": list(feedback.related_chunk_ids or []),
            "extraction_confidence": confidence,
            "extraction_payload": proposal,
        })
    return result


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = sum(float(a) * float(a) for a in left) ** 0.5
    right_norm = sum(float(b) * float(b) for b in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _deduplicate_evidence(
    rows: List[RagTermMappingEvidence],
) -> List[RagTermMappingEvidence]:
    """同一问题指纹只保留最早的一条证据，避免重复问题放大证据数。"""
    by_fingerprint: Dict[str, RagTermMappingEvidence] = {}
    for row in sorted(
        rows,
        key=lambda item: item.created_time.isoformat() if item.created_time else "",
    ):
        by_fingerprint.setdefault(row.query_fingerprint, row)
    return list(by_fingerprint.values())


async def _independent_component(rows: List[RagTermMappingEvidence]) -> List[RagTermMappingEvidence]:
    """选出相互相近的独立证据组，避免 A-B-C 的间接相似传递。"""
    eligible_rows = [
        row for row in rows
        if float(row.extraction_confidence or 0.0)
        >= PROJECT_CONFIG.MAPPING_EVIDENCE_MIN_CONFIDENCE
    ]
    unique_rows = _deduplicate_evidence(eligible_rows)
    if len(unique_rows) <= 1:
        return unique_rows
    vectors = await embed_texts([row.query_text for row in unique_rows], quick=True)
    threshold = PROJECT_CONFIG.MAPPING_EVIDENCE_MIN_SCORE

    def compatible(left: int, right: int) -> bool:
        left_en = normalize_term(unique_rows[left].official_en or "")
        right_en = normalize_term(unique_rows[right].official_en or "")
        return not (left_en and right_en and left_en != right_en)

    def center(indices: List[int]) -> List[float]:
        # 平均向量是组中心；_cosine 会自行归一化，无须改变原向量。
        return [
            sum(float(vectors[index][dimension]) for index in indices) / len(indices)
            for dimension in range(len(vectors[0]))
        ]

    best: List[int] = []
    # 每条证据都尝试作起点，按与起点的相似度加入。入组必须与所有现有
    # 成员以及新组中心达标，不能借一条中间证据把不相似的问题串起来。
    for seed in range(len(unique_rows)):
        group = [seed]
        candidates = sorted(
            (index for index in range(len(unique_rows)) if index != seed),
            key=lambda index: (-_cosine(vectors[seed], vectors[index]), index),
        )
        for candidate in candidates:
            if any(
                not compatible(candidate, member)
                or _cosine(vectors[candidate], vectors[member]) < threshold
                for member in group
            ):
                continue
            proposed = group + [candidate]
            group_center = center(proposed)
            if all(
                _cosine(vectors[index], group_center)
                >= PROJECT_CONFIG.MAPPING_EVIDENCE_CENTROID_MIN_SCORE
                for index in proposed
            ):
                group = proposed
        if len(group) > len(best):
            best = group
    return [unique_rows[index] for index in best]


class MappingEvidenceService:
    """采纳反馈到程序映射自动激活的异步流水线。

    适用范围只作为证据和结果的描述信息保存，不作为当前信用卡知识库
    中合并程序映射的硬性分区条件。
    """

    async def _source_conflict(self, proposal: Dict[str, Any]) -> str:
        """按“别名 -> 标准词”检查人工映射覆盖和冲突。

        人工表已有标准词本身，并不代表它已经覆盖了所有程序发现的
        别名。只有每个候选别名都在人工表中指向同一标准词时才返回
        ``covered``；出现同名别名指向其他标准词时返回 ``conflict``；
        只要存在人工表没有的新别名，就允许返回 ``valid``。
        """
        rows = await RagTermMappingSource.filter(status="enabled").all()
        canonical_key = normalize_term(proposal["canonical_zh"])
        alias_keys = {
            normalize_term(value)
            for value in proposal.get("aliases_zh") or []
            if normalize_term(value)
        }
        if not alias_keys:
            return "valid"

        covered_aliases: set[str] = set()
        for row in rows:
            row_canonical = normalize_term(row.canonical_zh)
            row_aliases = {
                normalize_term(value)
                for value in [row.canonical_zh, *(row.aliases_zh or [])]
                if normalize_term(value)
            }
            matched_aliases = alias_keys & row_aliases
            if not matched_aliases:
                continue
            if row_canonical != canonical_key:
                return "conflict"
            covered_aliases.update(matched_aliases)

        return "covered" if covered_aliases == alias_keys else "valid"

    async def _save_evidence(self, feedback: RagAnswerFeedback, proposal: Dict[str, Any]) -> RagTermMappingEvidence:
        status = await self._source_conflict(proposal)
        existing = await RagTermMappingEvidence.filter(
            feedback_uid=feedback.feedback_uid,
            mapping_key=proposal["mapping_key"],
        ).first()
        values = {
            "query_fingerprint": feedback.query_fingerprint,
            "query_text": feedback.resolved_query or feedback.original_query or "",
            "original_query": feedback.original_query or feedback.resolved_query or "",
            "alias_text": proposal["aliases_zh"][0],
            "alias_normalized": normalize_term(proposal["aliases_zh"][0]),
            "canonical_zh": proposal["canonical_zh"],
            "aliases_zh": proposal["aliases_zh"],
            "official_en": proposal["official_en"],
            "aliases_en": proposal["aliases_en"],
            "scope": proposal["scope"],
            "normalized_keys": proposal["normalized_keys"],
            "supporting_doc_ids": proposal["supporting_doc_ids"],
            "supporting_chunk_ids": proposal["supporting_chunk_ids"],
            "extraction_confidence": proposal["extraction_confidence"],
            "extraction_payload": proposal["extraction_payload"],
            "status": status,
            "algorithm_version": _ALGORITHM_VERSION,
            "error_message": None,
        }
        if existing is None:
            return await RagTermMappingEvidence.create(
                evidence_id=f"evi-{uuid4().hex}",
                feedback_uid=feedback.feedback_uid,
                mapping_key=proposal["mapping_key"],
                **values,
            )
        for key, value in values.items():
            setattr(existing, key, value)
        await existing.save()
        return existing

    @staticmethod
    async def _disable_existing(
        existing: Optional[RagTermMappingLearned],
        evidence: Sequence[RagTermMappingEvidence],
    ) -> Optional[RagTermMappingLearned]:
        """证据不足或相互冲突时，清晰地停用已有程序映射。"""
        if existing is None:
            return None
        existing.evidence_count = len(evidence)
        existing.source_feedback_ids = [row.feedback_uid for row in evidence]
        existing.status = "disabled"
        await existing.save(update_fields=[
            "evidence_count", "source_feedback_ids", "status", "updated_time",
        ])
        return existing

    async def _aggregate(self, mapping_key: str) -> Optional[RagTermMappingLearned]:
        """串行聚合同一映射，并在跨进程并发创建时重查已有记录。"""
        # pytest/ASGI 可能在不同事件循环中复用服务单例，锁必须按事件循环隔离。
        lock_key = (id(asyncio.get_running_loop()), mapping_key)
        lock = _mapping_aggregate_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            return await self._aggregate_unlocked(mapping_key)

    async def _aggregate_unlocked(self, mapping_key: str) -> Optional[RagTermMappingLearned]:
        existing = await RagTermMappingLearned.filter(mapping_key=mapping_key).first()
        rows = await RagTermMappingEvidence.filter(mapping_key=mapping_key, status="valid").all()
        if not rows:
            return await self._disable_existing(existing, [])
        feedback_ids = [row.feedback_uid for row in rows]
        feedback_rows = await RagAnswerFeedback.filter(feedback_uid__in=feedback_ids).all()
        valid_feedback = {
            row.feedback_uid: row
            for row in feedback_rows
            if row.action == "accepted" and row.index_status != "deleted"
        }
        rows = [row for row in rows if row.feedback_uid in valid_feedback]
        eligible_rows = [
            row for row in rows
            if float(row.extraction_confidence or 0.0)
            >= PROJECT_CONFIG.MAPPING_EVIDENCE_MIN_CONFIDENCE
        ]
        unique_rows = _deduplicate_evidence(eligible_rows)
        if not unique_rows:
            return await self._disable_existing(existing, [])

        official_terms = {
            normalize_term(row.official_en)
            for row in unique_rows
            if normalize_term(row.official_en)
        }
        if len(official_terms) > 1:
            LOGGER.warning(
                "程序映射存在多个官方英文词，暂不激活: mapping_key=%s, official_en=%s",
                mapping_key,
                sorted(official_terms),
            )
            return await self._disable_existing(existing, unique_rows)

        component = await _independent_component(unique_rows)
        if len(component) < PROJECT_CONFIG.LEARNED_MAPPING_MIN_EVIDENCE:
            return await self._disable_existing(existing, component)

        first = component[0]
        aliases_zh = _unique(value for row in component for value in (row.aliases_zh or []))
        aliases_en = _unique(value for row in component for value in (row.aliases_en or []))
        official_en = next((row.official_en for row in component if row.official_en), None)
        normalized_keys = _unique([
            first.canonical_zh,
            *aliases_zh,
            official_en or "",
            *aliases_en,
        ])
        confidence = min(
            0.99,
            max(0.5, sum(float(row.extraction_confidence or 0.5) for row in component) / len(component))
            + 0.1 * (len(component) - 1),
        )
        source_ids = [row.feedback_uid for row in component]
        merged_scopes = _unique(row.scope for row in component if row.scope)
        merged_scope = "；".join(merged_scopes) or None
        values = {
            "canonical_zh": first.canonical_zh,
            "aliases_zh": aliases_zh,
            "official_en": official_en,
            "aliases_en": aliases_en,
            "scope": merged_scope,
            "normalized_keys": normalized_keys,
            "evidence_count": len(component),
            "confidence": confidence,
            "source_feedback_ids": source_ids,
            "algorithm_version": _ALGORITHM_VERSION,
        }

        async def update_existing(row: RagTermMappingLearned) -> RagTermMappingLearned:
            for key, value in values.items():
                setattr(row, key, value)
            # 达到独立证据阈值后自动生效；明确被管理员停用/驳回的记录不自动复活。
            if row.reviewed_by is None and row.status in {"candidate", "disabled", "rejected"}:
                row.status = "active"
            await row.save()
            return row

        if existing is None:
            try:
                existing = await RagTermMappingLearned.create(
                    learned_mapping_id=f"learned-{uuid5(NAMESPACE_URL, mapping_key).hex[:32]}",
                    mapping_key=mapping_key,
                    **values,
                    status="active",
                )
            except IntegrityError:
                # 另一个进程可能刚刚创建了相同 mapping_key。不要把本次任务
                # 标记为失败，重查后把最新聚合结果写入同一条记录。
                existing = await RagTermMappingLearned.filter(mapping_key=mapping_key).first()
                if existing is None:
                    raise
                return await update_existing(existing)
        else:
            return await update_existing(existing)
        return existing

    async def process_feedback(self, feedback_uid: str) -> Dict[str, Any]:
        feedback = await RagAnswerFeedback.filter(feedback_uid=feedback_uid).first()
        if feedback is None:
            return {"success": False, "status": "missing", "feedback_uid": feedback_uid}
        if feedback.action != "accepted" or feedback.index_status == "deleted":
            evidence = await RagTermMappingEvidence.filter(feedback_uid=feedback_uid).all()
            mapping_keys = {row.mapping_key for row in evidence}
            for row in evidence:
                row.status = "revoked"
                await row.save(update_fields=["status", "updated_time"])
            for mapping_key in mapping_keys:
                await self._aggregate(mapping_key)
            feedback.mapping_extract_status = "revoked"
            feedback.mapping_extract_error = None
            await feedback.save(update_fields=["mapping_extract_status", "mapping_extract_error", "updated_time"])
            return {"success": True, "status": "revoked", "feedback_uid": feedback_uid}

        if not PROJECT_CONFIG.MAPPING_EXTRACTION_ENABLED:
            feedback.mapping_extract_status = "no_candidate"
            await feedback.save(update_fields=["mapping_extract_status", "updated_time"])
            return {"success": True, "status": "disabled", "feedback_uid": feedback_uid}

        if not feedback.query_fingerprint:
            feedback.query_fingerprint = query_fingerprint(feedback.resolved_query or feedback.original_query)
            await feedback.save(update_fields=["query_fingerprint", "updated_time"])
        try:
            proposals = await _extract_proposals(feedback)
            if not proposals:
                feedback.mapping_extract_status = "no_candidate"
                feedback.mapping_extract_error = None
                await feedback.save(update_fields=["mapping_extract_status", "mapping_extract_error", "updated_time"])
                return {"success": True, "status": "no_candidate", "feedback_uid": feedback_uid}
            candidates: List[str] = []
            for proposal in proposals:
                evidence = await self._save_evidence(feedback, proposal)
                if evidence.status == "valid":
                    await self._aggregate(evidence.mapping_key)
                    candidates.append(evidence.mapping_key)
            feedback.mapping_extract_status = "succeeded"
            feedback.mapping_extract_error = None
            await feedback.save(update_fields=["mapping_extract_status", "mapping_extract_error", "updated_time"])
            return {"success": True, "status": "succeeded", "feedback_uid": feedback_uid, "mapping_keys": candidates}
        except Exception as exc:
            feedback.mapping_extract_status = "failed"
            feedback.mapping_extract_error = f"{type(exc).__name__}: {exc}"[:2000]
            await feedback.save(update_fields=["mapping_extract_status", "mapping_extract_error", "updated_time"])
            LOGGER.error("采纳反馈映射证据处理失败: %s, %s", feedback_uid, exc)
            return {"success": False, "status": "failed", "feedback_uid": feedback_uid, "error": str(exc)}


mapping_evidence_service = MappingEvidenceService()
