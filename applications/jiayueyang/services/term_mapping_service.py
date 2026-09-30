# -*- coding: utf-8 -*-
"""术语映射确定性匹配服务。

该服务只负责从两张映射表找出确定的映射，不负责调用大模型或改写查询。
用户上传的权威映射始终优先于程序归纳映射。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from configure import LOGGER, PROJECT_CONFIG

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
    field_match_type: Optional[str] = None
    field_keys: Optional[List[str]] = None
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
            "field_match_type": self.field_match_type,
            "field_keys": list(self.field_keys or []),
            "status": self.status,
        }


MappingCandidate = Tuple[MappingMatch, int, int, int, int]

_FIELD_RE = re.compile(
    r"\b(?:field|de|f)\s*(\d{1,3}(?:\.\d+)?)"
    r"|字段\s*(\d{1,3}(?:\.\d+)?)(?:\s*域)?"
    r"|(?<![A-Za-z0-9.])(\d{1,3}(?:\.\d+)?)\s*域",
    re.IGNORECASE,
)


def _field_value(match: re.Match[str]) -> str:
    return next((group for group in match.groups() if group), "").strip()


def extract_field_variants(text: str) -> Set[str]:
    """查询侧统一 Field/DE/F/中文“域”写法；不修改数据库规范化值。"""
    values: Set[str] = set()
    for match in _FIELD_RE.finditer(text or ""):
        value = _field_value(match)
        if value:
            values.add(f"field:{value}")
    return values


def normalize_mapping_query(query: str) -> str:
    """仅供查询匹配使用的规范形式，不影响导入去重或 mapping_key。"""
    return normalize_term(query)


def _field_occurrence(query: str, field_key: str) -> Tuple[str, int, int]:
    wanted = field_key.split(":", 1)[-1]
    for match in _FIELD_RE.finditer(query or ""):
        value = _field_value(match)
        if value == wanted:
            return match.group(0), match.start(), match.end()
    return field_key, 0, max(1, len(field_key))


def _is_parent_field(value: str) -> bool:
    return "." not in value


def _field_expansion_requested(query: str) -> bool:
    return bool(re.search(r"有哪些?子域|包含哪些?子字段|子域|子字段", query or "", re.IGNORECASE))


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
        normalized_query = normalize_mapping_query(query)
        field_matching_enabled = bool(PROJECT_CONFIG.FIELD_VARIANT_NORMALIZATION_ENABLED)
        query_fields = extract_field_variants(query) if field_matching_enabled else set()
        expand_children = _field_expansion_requested(query)
        candidates: List[MappingCandidate] = []
        if not normalized_query:
            return candidates

        for row in rows:
            row_terms = self._row_terms(row)
            row_fields = (
                extract_field_variants(" ".join(item[1] for item in row_terms))
                if field_matching_enabled else set()
            )
            field_match_type: Optional[str] = None
            if query_fields and row_fields:
                exact_fields = query_fields & row_fields
                if exact_fields:
                    field_match_type = "exact"
                elif expand_children and any(_is_parent_field(qf) and rf.startswith(qf + ".") for qf in query_fields for rf in row_fields):
                    field_match_type = "parent_expansion"
                elif any(_is_parent_field(rf) and any(qf.startswith(rf + ".") for qf in query_fields) for rf in row_fields):
                    # 子字段查询暂时保留父字段候选，resolve() 会在没有精确子字段时才放行。
                    field_match_type = "parent_fallback"
                else:
                    continue
            # 人工标准词精确命中 > 字段键等价 > 普通别名命中。
            term_candidates = [item for item in row_terms if item[0] in normalized_query]
            term_candidates.sort(
                key=lambda item: (
                    1 if item[2] in ("canonical_zh", "official_en") else 0,
                    len(item[0]),
                ),
                reverse=True,
            )
            selected = term_candidates[0] if term_candidates else None
            if selected:
                normalized_value, matched_value, matched_field = selected
                start = normalized_query.find(normalized_value)
                end = start + len(normalized_value)
                match_type = "normalized_exact"
                match_priority = 3 if matched_field in ("canonical_zh", "official_en") else 1
            elif field_match_type:
                # 字段写法不同也可独立命中，不再要求映射行完整术语必须是查询子串。
                query_key = next(
                    (
                        qf for qf in sorted(query_fields)
                        if qf in row_fields
                        or (field_match_type == "parent_expansion" and any(rf.startswith(qf + ".") for rf in row_fields))
                        or (field_match_type == "parent_fallback" and any(qf.startswith(rf + ".") for rf in row_fields))
                    ),
                    sorted(query_fields)[0],
                )
                matched_value, start, end = _field_occurrence(query, query_key)
                matched_field = "字段键等价"
                match_type = "field_equivalent"
                match_priority = 2
            else:
                continue
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
                match_type=match_type,
                field_match_type=field_match_type,
                field_keys=sorted(row_fields),
            )
            candidates.append((match, start, end, rank, match_priority))
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
            scoped = [candidate for candidate in candidates_at_span if candidate[3] == best_rank]
            best_priority = max(candidate[4] for candidate in scoped)
            best = [candidate[0] for candidate in scoped if candidate[4] == best_priority]
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
            source_candidates = self._candidate_rows(query, source_rows, "source_mapping", scope)
            learned_rows = await RagTermMappingLearned.filter(status=self._LEARNED_STATUS).all()
            learned_candidates = self._candidate_rows(query, learned_rows, "learned_mapping", scope)
            all_candidates = source_candidates + learned_candidates
            has_exact_field = any(item[0].field_match_type in ("exact", "parent_expansion") for item in all_candidates)
            if has_exact_field:
                source_candidates = [item for item in source_candidates if item[0].field_match_type != "parent_fallback"]
                learned_candidates = [item for item in learned_candidates if item[0].field_match_type != "parent_fallback"]
            source_matches, source_conflicts, occupied = self._select_candidates(
                source_candidates,
                "source_mapping", [],
            )
            learned_matches, learned_conflicts, _ = self._select_candidates(
                learned_candidates,
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

