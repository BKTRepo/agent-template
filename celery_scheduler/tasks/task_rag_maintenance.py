# -*- coding: utf-8 -*-
"""RAG 文档维护任务: 周期性巡检僵尸（失联）任务 + 孤儿分块 GC。

Web 启动巡检覆盖"启动时点", 本周期任务覆盖"运行期间": Worker 进程崩溃 /
整机宕机等导致任务中途失联、终态未写入时, 巡检依据心跳账龄 + Celery
任务状态判定任务已确定性死亡后标记 failed, 用户可在前端看到并点击重试。

孤儿分块 GC: 向量库中 doc_id 已不存在于文档表的分块（历史删除流程的
残留、异常中断的写入等）, 低频对账清理, 防止检索被无主旧块污染。
"""
import asyncio
from typing import Any, Dict

from celery_scheduler.celery_worker import celery
from configure import LOGGER


@celery.task(name="celery_scheduler.tasks.task_rag_maintenance.sweep_stale_documents_task")
async def sweep_stale_documents_task() -> Dict[str, Any]:
    """巡检确定性失联的任务并标记失败（判定规则见 RagDocumentService.sweep_stale_documents）。"""
    try:
        from applications.jiayueyang.services.rag_service import RagDocumentService

        marked = await RagDocumentService().sweep_stale_documents()
        return {"success": True, "marked_failed": marked}
    except Exception as exc:
        LOGGER.error(f"僵尸任务巡检失败: {type(exc).__name__}: {exc}")
        return {"success": False, "error": str(exc)}


@celery.task(name="celery_scheduler.tasks.task_rag_maintenance.gc_orphan_chunks_task")
async def gc_orphan_chunks_task() -> Dict[str, Any]:
    """孤儿分块 GC: 向量集合现存 doc_id 与文档表对账, 删除无主分块。

    安全边界（宁漏勿错）:
    - 集合查询失败（返回 None）→ 本轮跳过, 绝不把"查不到"当成"全孤儿";
    - 仅删除文档表中**不存在**的 doc_id——处理中的文档必然在文档表中,
      不会误删在途写入;
    - 单个 doc_id 删除失败仅记录, 不影响其余清理。
    """
    try:
        from applications.jiayueyang.models.rag_document_model import RagDocument
        from applications.jiayueyang.rag.milvus_store import (
            delete_by_doc_id,
            list_collection_doc_ids,
        )

        # 同步向量库调用移交线程池, 不阻塞任务常驻事件循环
        collection_ids = await asyncio.to_thread(list_collection_doc_ids)
        if collection_ids is None:
            return {"success": False, "error": "向量集合查询失败, 本轮跳过 GC"}
        if not collection_ids:
            return {"success": True, "removed": 0}

        db_ids = set(await RagDocument.all().values_list("job_id", flat=True))
        orphans = sorted(collection_ids - db_ids)
        removed = 0
        for doc_id in orphans:
            deleted = await asyncio.to_thread(delete_by_doc_id, doc_id)
            if deleted >= 0:
                removed += 1
                LOGGER.warning(
                    f"孤儿分块 GC: 清理无主向量分块 doc_id={doc_id} ({deleted} 块)"
                )
        if orphans:
            LOGGER.info(f"孤儿分块 GC 完成: 清理 {removed}/{len(orphans)} 个无主 doc_id")
        return {"success": True, "removed": removed, "orphans": orphans}
    except Exception as exc:
        LOGGER.error(f"孤儿分块 GC 失败: {type(exc).__name__}: {exc}")
        return {"success": False, "error": str(exc)}
