# -*- coding: utf-8 -*-
"""术语映射确定性匹配服务。

该服务只负责从两张映射表找出确定的映射，不负责调用大模型或改写查询。
用户上传的权威映射始终优先于程序归纳映射。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from configure import LOGGER

from applications.jiayueyang.models.term_mapping_model import (
    RagTermMappingLearned,
    RagTermMappingSource,
)
from applications.jiayueyang.services.term_mapping_import_service import normalize_term


@dataclass(frozen=True)
class MappingMatch:
    """一个确定命中的映射结果。"""

    mapping_id: str
    mapping_source: str
    canonical_zh: str
    official_en: Optional[str]
    aliases_en: List[str]
    scope: Optional[str]
    matched_value: str
    matched_field: str
    match_type: str
    status: str = "determined"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "mapping_source": self.mapping_source,
            "canonical_zh": self.canonical_zh,
            "official_en": self.official_en,
            "aliases_en": self.aliases_en,
            "scope": self.scope,
            "matched_value": self.matched_value,
            "matched_field": self.matched_field,
            "match_type": self.match_type,
            "status": self.status,
        }


MappingCandidate = Tuple[MappingMatch, int, int, int]


class TermMappingService:
    """先收集所有人工术语，再用 active 程序映射补充未覆盖的术语。"""

    _SOURCE_STATUS = "enabled"
    _LEARNED_STATUS = "active"

    @staticmethod
    def _row_terms(row: Any) -> List[Tuple[str, str, str]]:
        """返回 (规范化值, 原始值, 字段名)，按匹配优先级排列。"""
        values: List[Tuple[str, str, str]] = [
            ("canonical_zh", row.canonical_zh or "", "中文标准词"),
            ("official_en", row.official_en or "", "官方英文词"),
        ]
        for value in row.aliases_zh or []:
            values.append(("aliases_zh", value or "", "中文别名"))
        for value in row.aliases_en or []:
            values.append(("aliases_en", value or "", "英文别名/缩写"))
        return [
            (normalized, original, field)
            for field, original, _label in values
            if (normalized := normalize_term(original))
        ]

    @staticmethod
    def _scope_rank(row_scope: Optional[str], requested_scope: Optional[str]) -> int:
        if not requested_scope:
            return 1
        actual = normalize_term(row_scope)
        wanted = normalize_term(requested_scope)
        if actual == wanted:
            return 2
        # Scope is optional metadata for this credit-card knowledge base. A
        # different or missing scope must not discard an otherwise valid
        # mapping; an exact scope only gets a preference when available.
        return 1

    @staticmethod
    def _row_id(row: Any, source: str) -> str:
        return row.mapping_id if source == "source_mapping" else row.learned_mapping_id

    def _candidate_rows(
        self,
        query: str,
        rows: Iterable[Any],
        source: str,
        requested_scope: Optional[str],
    ) -> List[MappingCandidate]:
        normalized_query = normalize_term(query)
        candidates: List[MappingCandidate] = []
        if not normalized_query:
            return candidates

        for row in rows:
            row_terms = self._row_terms(row)
            # 最长词优先，避免 “auth” 抢在 “incremental auth” 前面。
            row_terms.sort(key=lambda item: len(item[0]), reverse=True)
            selected = next(
                (item for item in row_terms if item[0] in normalized_query),
                None,
            )
            if not selected:
                continue
            normalized_value, matched_value, matched_field = selected
            start = normalized_query.find(normalized_value)
            rank = self._scope_rank(row.scope, requested_scope)
            match = MappingMatch(
                mapping_id=self._row_id(row, source),
                mapping_source=source,
                canonical_zh=row.canonical_zh,
                official_en=row.official_en,
                aliases_en=list(row.aliases_en or []),
                scope=row.scope,
                matched_value=matched_value,
                matched_field=matched_field,
                match_type="normalized_exact",
            )
            candidates.append((match, start, start + len(normalized_value), rank))
        return candidates

    @staticmethod
    def _select_candidates(
        candidates: List[MappingCandidate],
        source: str,
        occupied: List[Tuple[int, int]],
    ) -> Tuple[List[MappingMatch], List[Dict[str, Any]], List[Tuple[int, int]]]:
        """只在同一词语位置比较冲突，其他位置可以各自命中映射。"""
        by_span: Dict[Tuple[int, int], List[MappingCandidate]] = {}
        for candidate in candidates:
            by_span.setdefault((candidate[1], candidate[2]), []).append(candidate)

        matches: List[MappingMatch] = []
        conflicts: List[Dict[str, Any]] = []
        spans = list(occupied)
        for start, end in sorted(by_span, key=lambda span: (span[0] - span[1], span[0])):
            if any(start < used_end and used_start < end for used_start, used_end in spans):
                continue
            candidates_at_span = by_span[(start, end)]
            best_rank = max(candidate[3] for candidate in candidates_at_span)
            best = [candidate[0] for candidate in candidates_at_span if candidate[3] == best_rank]
            canonical_terms = {normalize_term(item.canonical_zh) for item in best}
            if len(canonical_terms) > 1:
                conflicts.append({
                    "mapping_source": source,
                    "status": "conflict",
                    "candidates": [item.to_dict() for item in best],
                })
            else:
                matches.append(min(best, key=lambda item: item.mapping_id))
            spans.append((start, end))
        # 一个映射在问题里可出现多次，改写提示只需要一份。
        unique = {match.mapping_id: match for match in matches}
        return list(unique.values()), conflicts, spans

    async def resolve(
        self,
        query: str,
        scope: Optional[str] = None,
    ) -> Dict[str, Any]:
        """解析问题中的术语映射。

        返回 ``determined``、``conflict``、``unmatched`` 或 ``unavailable``，
        调用方可以在后三种情况继续走现有 LLM 查询改写流程。
        """
        if not normalize_term(query):
            return {"status": "unmatched", "matches": [], "conflicts": []}
        try:
            source_rows = await RagTermMappingSource.filter(status=self._SOURCE_STATUS).all()
            source_matches, source_conflicts, occupied = self._select_candidates(
                self._candidate_rows(query, source_rows, "source_mapping", scope),
                "source_mapping", [],
            )

            learned_rows = await RagTermMappingLearned.filter(status=self._LEARNED_STATUS).all()
            learned_matches, learned_conflicts, _ = self._select_candidates(
                self._candidate_rows(query, learned_rows, "learned_mapping", scope),
                "learned_mapping", occupied,
            )
            matches = source_matches + learned_matches
            conflicts = source_conflicts + learned_conflicts
            return {
                "status": "conflict" if conflicts else ("determined" if matches else "unmatched"),
                "matches": [match.to_dict() for match in matches],
                "conflicts": conflicts,
            }
        except Exception as exc:
            # 映射服务不可用时不阻断现有问答链路。
            LOGGER.warning("术语映射服务不可用，回退现有查询改写: %s", exc)
            return {"status": "unavailable", "matches": [], "conflicts": [], "error": str(exc)}


term_mapping_service = TermMappingService()

