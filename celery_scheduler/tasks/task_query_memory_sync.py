# -*- coding: utf-8 -*-
"""查询经验索引同步任务。"""

from typing import Any, Dict

from celery_scheduler.celery_worker import celery
from applications.jiayueyang.services.query_memory_sync import query_memory_sync_service
from configure import LOGGER


@celery.task(name="celery_scheduler.tasks.task_query_memory_sync.sync_pending_query_memory_task")
async def sync_pending_query_memory_task(limit: int = 100) -> Dict[str, Any]:
    """周期性同步 pending/failed 采纳反馈；可重复执行。"""
    try:
        return await query_memory_sync_service.sync_pending_feedback(limit=limit)
    except Exception as exc:
        LOGGER.error(f"查询经验批量同步失败: {type(exc).__name__}: {exc}")
        return {"success": False, "error": str(exc)}


@celery.task(name="celery_scheduler.tasks.task_query_memory_sync.sync_query_memory_record_task")
async def sync_query_memory_record_task(source_type: str, source_id: str) -> Dict[str, Any]:
    """同步单条反馈或映射记录；事务提交后再由调用方投递。"""
    try:
        if source_type == "accepted_feedback":
            return await query_memory_sync_service.sync_feedback(source_id)
        if source_type == "source_mapping":
            return await query_memory_sync_service.sync_mapping(source_id, learned=False)
        if source_type == "learned_mapping":
            return await query_memory_sync_service.sync_mapping(source_id, learned=True)
        return {"success": False, "status": "failed", "error": f"不支持的 source_type: {source_type}"}
    except Exception as exc:
        LOGGER.error(f"查询经验单条同步失败: {source_type}/{source_id}, {type(exc).__name__}: {exc}")
        return {"success": False, "status": "failed", "error": str(exc)}

