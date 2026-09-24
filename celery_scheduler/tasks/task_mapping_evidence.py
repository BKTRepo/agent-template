# -*- coding: utf-8 -*-
"""采纳反馈映射证据提取与重试任务。"""

from typing import Any, Dict

from celery_scheduler.celery_worker import celery
from applications.jiayueyang.models.feedback_model import RagAnswerFeedback
from applications.jiayueyang.services.mapping_evidence_service import mapping_evidence_service
from configure import LOGGER


@celery.task(name="celery_scheduler.tasks.task_mapping_evidence.process_mapping_evidence_task")
async def process_mapping_evidence_task(feedback_uid: str) -> Dict[str, Any]:
    try:
        return await mapping_evidence_service.process_feedback(feedback_uid)
    except Exception as exc:
        LOGGER.error("映射证据单条任务失败: %s, %s", feedback_uid, exc)
        return {"success": False, "status": "failed", "feedback_uid": feedback_uid, "error": str(exc)}


@celery.task(name="celery_scheduler.tasks.task_mapping_evidence.extract_mapping_evidence_task")
async def extract_mapping_evidence_task(feedback_uid: str) -> Dict[str, Any]:
    """显式任务名：从单条采纳反馈提取并保存映射证据。"""
    return await mapping_evidence_service.process_feedback(feedback_uid)


@celery.task(name="celery_scheduler.tasks.task_mapping_evidence.aggregate_learned_mapping_task")
async def aggregate_learned_mapping_task(mapping_key: str) -> Dict[str, Any]:
    """显式任务名：按 mapping_key 重新计算独立证据并更新程序候选。"""
    try:
        learned = await mapping_evidence_service._aggregate(mapping_key)
        return {
            "success": True,
            "mapping_key": mapping_key,
            "learned_mapping_id": learned.learned_mapping_id if learned else None,
            "evidence_count": learned.evidence_count if learned else 0,
        }
    except Exception as exc:
        LOGGER.error("程序映射聚合任务失败: %s, %s", mapping_key, exc)
        return {"success": False, "mapping_key": mapping_key, "status": "failed", "error": str(exc)}


@celery.task(name="celery_scheduler.tasks.task_mapping_evidence.sweep_mapping_evidence_task")
async def sweep_mapping_evidence_task(limit: int = 100) -> Dict[str, Any]:
    """补偿采纳后任务投递失败、Embedding/LLM 临时失败和取消采纳。"""
    rows = await RagAnswerFeedback.filter(
        mapping_extract_status__in=["pending", "failed", "revoke_pending"],
    ).order_by("created_time").limit(max(1, min(int(limit), 500)))
    results = [await mapping_evidence_service.process_feedback(row.feedback_uid) for row in rows]
    return {
        "success": all(item.get("success") for item in results) if results else True,
        "processed": len(results),
        "succeeded": sum(item.get("status") == "succeeded" for item in results),
        "revoked": sum(item.get("status") == "revoked" for item in results),
        "failed": sum(item.get("status") == "failed" for item in results),
    }


@celery.task(name="celery_scheduler.tasks.task_mapping_evidence.retry_failed_mapping_extraction_task")
async def retry_failed_mapping_extraction_task(limit: int = 100) -> Dict[str, Any]:
    """只补偿失败任务，方便部署环境单独观察重试效果。"""
    rows = await RagAnswerFeedback.filter(
        mapping_extract_status__in=["failed", "pending", "revoke_pending"],
    ).order_by("updated_time").limit(max(1, min(int(limit), 500)))
    results = [await mapping_evidence_service.process_feedback(row.feedback_uid) for row in rows]
    return {
        "success": all(item.get("success") for item in results) if results else True,
        "processed": len(results),
        "succeeded": sum(item.get("status") == "succeeded" for item in results),
        "revoked": sum(item.get("status") == "revoked" for item in results),
        "failed": sum(item.get("status") == "failed" for item in results),
    }
