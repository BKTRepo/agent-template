# -*- coding: utf-8 -*-
"""术语映射表的独立 CRUD 服务。

这里刻意使用两个服务类，避免把用户上传的权威数据和程序归纳数据
放进同一套写入入口。后续上传、反馈归纳和审核接口应分别调用对应的类。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type

from tortoise.exceptions import IntegrityError

from applications.jiayueyang.models.term_mapping_model import (
    RagTermMappingLearned,
    RagTermMappingSource,
)
from applications.jiayueyang.services.scaffold import ScaffoldCrud
from core.exceptions import DataAlreadyExistsException, ParameterException


class _TermMappingCrudBase(ScaffoldCrud):
    """两张映射表共用的只读查询和受控状态操作。"""

    STATUS_VALUES: frozenset[str] = frozenset()
    CREATE_FIELDS: frozenset[str] = frozenset()
    UPDATE_FIELDS: frozenset[str] = frozenset()
    EXTERNAL_ID_FIELD = "mapping_id"

    def _validate_status(self, status: str) -> str:
        if status not in self.STATUS_VALUES:
            raise ParameterException(
                message=f"{self.model.__name__} 不支持状态: {status}，可选值: {sorted(self.STATUS_VALUES)}"
            )
        return status

    @staticmethod
    def _clean_payload(payload: Dict[str, Any], allowed: frozenset[str]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ParameterException(message="映射数据必须是对象")
        unknown = set(payload) - allowed
        if unknown:
            raise ParameterException(message=f"映射数据包含不允许写入的字段: {sorted(unknown)}")
        return {key: value for key, value in payload.items() if value is not None}

    async def get_by_key(self, mapping_key: str, *, enabled_only: bool = False):
        query = self.model.filter(mapping_key=mapping_key)
        if enabled_only:
            query = query.filter(status="enabled" if self.model is RagTermMappingSource else "active")
        return await query.first()

    async def list_mappings(
        self,
        *,
        status: Optional[str] = None,
        scope: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> Tuple[int, List[Any]]:
        if page < 1 or page_size < 1 or page_size > 1000:
            raise ParameterException(message="page 必须从 1 开始，page_size 范围为 1-1000")
        if status is not None:
            self._validate_status(status)
        filters: Dict[str, Any] = {}
        if status is not None:
            filters["status"] = status
        if scope:
            filters["scope"] = scope
        query = self.model.filter(**filters).order_by("-updated_time", "id")
        return await query.count(), await query.offset((page - 1) * page_size).limit(page_size)

    async def create_mapping(self, payload: Dict[str, Any]):
        values = self._clean_payload(payload, self.CREATE_FIELDS)
        if not values.get(self.EXTERNAL_ID_FIELD):
            raise ParameterException(message=f"缺少必填字段: {self.EXTERNAL_ID_FIELD}")
        if not values.get("mapping_key"):
            raise ParameterException(message="缺少必填字段: mapping_key")
        try:
            return await self.model.create(**values)
        except IntegrityError as exc:
            raise DataAlreadyExistsException(message="映射编号或规范化匹配键已存在") from exc

    async def update_mapping(self, external_id: str, payload: Dict[str, Any]):
        values = self._clean_payload(payload, self.UPDATE_FIELDS)
        if not values:
            raise ParameterException(message="没有可更新的字段")
        obj = await self.model.filter(**{self.EXTERNAL_ID_FIELD: external_id}).first()
        if obj is None:
            raise ParameterException(message=f"映射不存在: {external_id}")
        for key, value in values.items():
            setattr(obj, key, value)
        try:
            await obj.save()
        except IntegrityError as exc:
            raise DataAlreadyExistsException(message="更新后的规范化匹配键已存在") from exc
        return obj

    async def set_status(self, external_id: str, status: str):
        self._validate_status(status)
        obj = await self.model.filter(**{self.EXTERNAL_ID_FIELD: external_id}).first()
        if obj is None:
            raise ParameterException(message=f"映射不存在: {external_id}")
        obj.status = status
        await obj.save(update_fields=["status", "updated_time"])
        return obj

    async def remove_mapping(self, external_id: str):
        obj = await self.model.filter(**{self.EXTERNAL_ID_FIELD: external_id}).first()
        if obj is None:
            raise ParameterException(message=f"映射不存在: {external_id}")
        await obj.delete()
        return obj


class RagTermMappingSourceCrud(_TermMappingCrudBase):
    """用户上传的权威映射 CRUD；程序反馈归纳流程不得调用此类写入。"""

    model: Type[RagTermMappingSource] = RagTermMappingSource
    STATUS_VALUES = frozenset({"enabled", "disabled"})
    CREATE_FIELDS = frozenset({
        "mapping_id", "mapping_key", "canonical_zh", "aliases_zh", "official_en",
        "aliases_en", "scope", "note", "raw_payload", "normalized_keys", "status",
        "upload_batch_id", "source_file", "source_row", "version", "created_by", "updated_by",
    })
    UPDATE_FIELDS = frozenset({
        "canonical_zh", "aliases_zh", "official_en", "aliases_en", "scope", "note",
        "raw_payload", "normalized_keys", "source_file", "source_row", "version", "updated_by",
    })
    EXTERNAL_ID_FIELD = "mapping_id"

    def __init__(self):
        super().__init__(model=RagTermMappingSource)

    async def disable(self, mapping_id: str):
        return await self.set_status(mapping_id, "disabled")

    async def enable(self, mapping_id: str):
        return await self.set_status(mapping_id, "enabled")


class RagTermMappingLearnedCrud(_TermMappingCrudBase):
    """程序根据采纳反馈归纳的映射 CRUD；不写入用户权威表。"""

    model: Type[RagTermMappingLearned] = RagTermMappingLearned
    STATUS_VALUES = frozenset({"candidate", "active", "rejected", "disabled"})
    CREATE_FIELDS = frozenset({
        "learned_mapping_id", "mapping_key", "canonical_zh", "aliases_zh", "official_en",
        "aliases_en", "scope", "normalized_keys", "evidence_count", "confidence", "status",
        "source_feedback_ids", "algorithm_version", "reviewed_by", "reviewed_time",
    })
    UPDATE_FIELDS = frozenset({
        "canonical_zh", "aliases_zh", "official_en", "aliases_en", "scope", "normalized_keys",
        "evidence_count", "confidence", "status", "source_feedback_ids", "algorithm_version",
        "reviewed_by", "reviewed_time",
    })
    EXTERNAL_ID_FIELD = "learned_mapping_id"

    def __init__(self):
        super().__init__(model=RagTermMappingLearned)

    async def disable(self, learned_mapping_id: str):
        return await self.set_status(learned_mapping_id, "disabled")

    async def activate(self, learned_mapping_id: str):
        return await self.set_status(learned_mapping_id, "active")

    async def reject(self, learned_mapping_id: str):
        return await self.set_status(learned_mapping_id, "rejected")

    async def review(self, learned_mapping_id: str, action: str, reviewer: str):
        """审核程序归纳映射，并留下审核人和审核时间。"""
        reviewer = (reviewer or "").strip()
        if not reviewer:
            raise ParameterException(message="审核人不能为空")
        action_to_status = {
            "activate": "active",
            "reject": "rejected",
            "disable": "disabled",
        }
        status = action_to_status.get(action)
        if status is None:
            raise ParameterException(message="action 只能是 activate、reject 或 disable")
        obj = await self.model.filter(learned_mapping_id=learned_mapping_id).first()
        if obj is None:
            raise ParameterException(message=f"程序映射不存在: {learned_mapping_id}")
        if action in {"activate", "reject"} and obj.status != "candidate":
            raise ParameterException(message=f"只有 candidate 状态可以执行 {action}")
        if action == "disable" and obj.status not in {"candidate", "active"}:
            raise ParameterException(message="只有 candidate 或 active 状态可以停用")
        obj.status = status
        obj.reviewed_by = reviewer
        obj.reviewed_time = datetime.now()
        await obj.save(update_fields=["status", "reviewed_by", "reviewed_time", "updated_time"])
        return obj


source_term_mapping_crud = RagTermMappingSourceCrud()
learned_term_mapping_crud = RagTermMappingLearnedCrud()
