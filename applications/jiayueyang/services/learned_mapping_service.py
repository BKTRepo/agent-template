# -*- coding: utf-8 -*-
"""程序映射候选入口。

真正的证据提取和聚合由 ``mapping_evidence_service`` 负责。本服务保留原有
from-feedback 接口，方便审核人员手动补偿一次失败的异步任务。
"""

from __future__ import annotations

from typing import List

from applications.jiayueyang.models.feedback_model import RagAnswerFeedback
from applications.jiayueyang.models.term_mapping_model import RagTermMappingLearned
from applications.jiayueyang.services.mapping_evidence_service import mapping_evidence_service
from core.exceptions import NotFoundException, ParameterException


class LearnedMappingService:
    async def from_feedback(self, feedback_uid: str) -> List[RagTermMappingLearned]:
        feedback = await RagAnswerFeedback.filter(feedback_uid=feedback_uid).first()
        if feedback is None:
            raise NotFoundException(message="采纳反馈不存在")
        if feedback.action != "accepted" or feedback.index_status == "deleted":
            raise ParameterException(message="只有有效的 accepted 反馈可以归纳映射")

        result = await mapping_evidence_service.process_feedback(feedback_uid)
        if not result.get("success"):
            raise ParameterException(message=result.get("error") or "映射证据提取失败")
        mapping_keys = result.get("mapping_keys") or []
        if not mapping_keys:
            return []
        return await RagTermMappingLearned.filter(mapping_key__in=mapping_keys).all()


learned_mapping_service = LearnedMappingService()
