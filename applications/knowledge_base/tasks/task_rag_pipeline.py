# -*- coding: utf-8 -*-
"""RAG 文档处理 Celery 任务（替代原 asyncio 后台任务）。

任务仅接收 job_id, 其余参数均从文档状态存储（MySQL keenrobot_rag_document 表）读取,
与 zsj 的 task_test_case_gen 等即发式任务范式一致。
"""
import traceback
from typing import Any, Dict

from celery.exceptions import SoftTimeLimitExceeded

from celery_scheduler.celery_worker import celery
from celery import current_task

def get_celery_execution_id():
    from celery_scheduler.celery_base import LOCAL_CONTEXT_VAR
    return LOCAL_CONTEXT_VAR.task_id or (getattr(current_task.request, "id", None) if current_task else None)

from configure import LOGGER


@celery.task(
    name="applications.knowledge_base.tasks.task_rag_pipeline.process_document_task",
    soft_time_limit=3300,
    time_limit=3600,
)
async def process_document_task(job_id: str) -> Dict[str, Any]:
    """Celery 入口: 按 job_id 后台执行文档处理流水线（解析 → 术语 → 多模态 → 分块 → 嵌入）。

    消息仅携带 job_id; 源文件字节流由 Worker 从提交时落盘的留档目录
    （input/<job_id>/）重新读取。

    :param job_id: 文档任务ID
    """
    try:
        from applications.knowledge_base.services.rag_pipeline import RagPipelineService
        from applications.knowledge_base.services.rag_service import RagDocumentService

        pipeline_service = RagPipelineService(document_service=RagDocumentService())
        # execution_token 传 Celery task id: 分布式锁以此判定重入
        # （acks_late 重投递任务 task_id 不变, 可接管续跑; 不同 token 的并行执行被拒）
        return await pipeline_service.process_document(
            job_id=job_id,
            execution_token=get_celery_execution_id() or process_document_task.request.id,
        )
    except SoftTimeLimitExceeded as exc:
        # 软超时仍有机会执行清理和状态回写：明确记录为失败并继续抛出，
        # 让 Celery 看到真实的 FAILURE，而不是把超时伪装成 SUCCESS。
        LOGGER.error(
            f"RAG 文档处理任务软超时: job_id={job_id}, "
            f"错误类型={type(exc).__name__}, 错误描述={exc}\n"
            f"错误回溯={traceback.format_exc()}"
        )
        try:
            from applications.knowledge_base.services.rag_service import RagDocumentService

            await RagDocumentService().update_document(job_id, {
                "status": "failed",
                "summary": "文档解析任务超时, 请重试",
                "error_trace": traceback.format_exc()[-5000:],
                "updated_at": RagDocumentService.now_time(),
            })
        except Exception as state_exc:
            LOGGER.error(
                f"文档解析超时状态回写失败: job_id={job_id}, "
                f"{type(state_exc).__name__}: {state_exc}"
            )
        raise
    except Exception as exc:
        LOGGER.error(
            f"RAG 文档处理任务异常: \n"
            f"job_id: {job_id}\n"
            f"错误类型: {type(exc).__name__}\n"
            f"错误描述: {exc}\n"
            f"错误回溯: {traceback.format_exc()}\n"
        )
        return {"success": False, "error": str(exc)}


@celery.task(
    name="applications.knowledge_base.tasks.task_rag_pipeline.rollback_document_task",
    soft_time_limit=1500,
    time_limit=1800,
)
async def rollback_document_task(job_id: str) -> Dict[str, Any]:
    """Celery 入口: 增量更新失败后, 把文档回滚到上一版本。

    执行体（RagPipelineService.execute_rollback）: 先用 prev 归档的
    embeddings.json 重写向量库, 再恢复产物/留档目录与文档字段。
    短任务（秒级~分钟级）, 时限远小于完整处理任务。

    :param job_id: 文档任务ID
    """
    try:
        from applications.knowledge_base.services.rag_pipeline import RagPipelineService
        from applications.knowledge_base.services.rag_service import RagDocumentService

        pipeline_service = RagPipelineService(document_service=RagDocumentService())
        return await pipeline_service.execute_rollback(
            job_id=job_id,
            execution_token=get_celery_execution_id() or rollback_document_task.request.id,
        )
    except Exception as exc:
        LOGGER.error(
            f"RAG 文档回滚任务异常: \n"
            f"job_id: {job_id}\n"
            f"错误类型: {type(exc).__name__}\n"
            f"错误描述: {exc}\n"
            f"错误回溯: {traceback.format_exc()}\n"
        )
        return {"success": False, "error": str(exc)}


@celery.task(
    name="applications.knowledge_base.tasks.task_rag_pipeline.delete_document_task",
    bind=True,
    max_retries=12,
    soft_time_limit=1500,
    time_limit=1800,
)
def delete_document_task(self, job_id: str) -> Dict[str, Any]:
    """独立删除队列；短暂故障定时重试，不占着执行槽等待解析结束。

    保持同步 Celery 入口，确保 retry() 在持有 request 的 Worker 线程调用。
    ORM 协程仍在该进程的常驻事件循环执行。
    """
    from celery_scheduler.celery_base import run_async
    from applications.knowledge_base.services.rag_service import (
        RagDocumentService, RetryableDeletionError,
    )
    service = RagDocumentService()
    try:
        result = run_async(service.delete_document_in_worker(
            job_id=job_id,
            execution_token=get_celery_execution_id() or self.request.id,
        ))
        LOGGER.info(f"【Celery】文档删除任务完成: job_id={job_id}, result={result}")
        return result
    except RetryableDeletionError as exc:
        retries = self.request.retries
        if retries >= self.max_retries:
            run_async(service.crud.record_deletion_failure(
                job_id, f"自动重试 {retries} 次后仍失败: {exc}",
                retryable=False, error_type="RetryExhausted",
            ))
            raise
        delay = min(30, 2 ** min(retries + 1, 5))
        run_async(service.crud.set_deletion_progress(
            job_id, f"删除暂未完成，{delay} 秒后第 {retries + 1}/{self.max_retries} 次重试：{exc}",
        ))
        raise self.retry(exc=exc, countdown=delay)
    except Exception as exc:
        LOGGER.error(
            f"【Celery】文档删除任务异常: job_id={job_id}, "
            f"错误类型={type(exc).__name__}, 错误描述={exc}\n"
            f"错误回溯={traceback.format_exc()}"
        )
        raise
