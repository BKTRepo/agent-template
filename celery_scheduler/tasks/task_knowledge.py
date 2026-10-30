"""适配源 RAG 的同步 Celery 删除入口，retry 必须发生在 Worker 请求线程。"""
from celery import Task

from celery_scheduler.celery_worker import celery
from celery_scheduler.celery_base import run_async, init_tortoise_orm
from applications.knowledge_base.models.knowledge_base_model import Document
from applications.knowledge_base.services.document_jobs import (
    PROCESS_TASK, DELETE_TASK, SWEEP_TASK, DocumentJobRunner, deletion_progress, sweep_jobs,
)
from applications.knowledge_base.services.job_control import RetryableDeletionError, NonRetryableDeletionError
from configure import PROJECT_CONFIG
from enums import DocumentStatus


async def _run(document_id, generation, deleting):
    await init_tortoise_orm()
    return await DocumentJobRunner().run(document_id, generation, deleting=deleting)


@celery.task(name=DELETE_TASK, bind=True, base=Task, max_retries=12, acks_late=True, reject_on_worker_lost=True)
def delete_document_task(self, document_id, generation):
    try:
        return run_async(_run(document_id, generation, True))
    except RetryableDeletionError as exc:
        request_retries = self.request.retries  # Celery request 为线程局部，先在 Worker 线程取值。
        async def plan():
            current = await Document.get_or_none(id=document_id)
            if not current or current.generation != generation:
                return None
            retries = max(request_retries, current.deletion_retry_count)
            limit = PROJECT_CONFIG.KNOWLEDGE_DELETE_MAX_RETRIES
            if retries >= limit:
                await deletion_progress(document_id, generation, retries=retries, terminal=True,
                    message=f"自动重试 {retries} 次后仍失败，请重试删除", error_type="RetryExhausted")
                return -1
            delay = min(30, 2 ** min(retries + 1, 5))
            await deletion_progress(document_id, generation, retries=retries + 1,
                message=f"删除暂未完成，{delay} 秒后自动重试", error_type=type(exc).__name__, delay=delay)
            return delay
        delay = run_async(plan())
        if delay is None:
            return {"status": "skipped"}
        if delay < 0:
            raise
        raise self.retry(exc=exc, countdown=delay, max_retries=PROJECT_CONFIG.KNOWLEDGE_DELETE_MAX_RETRIES)
    except NonRetryableDeletionError as exc:
        run_async(deletion_progress(document_id, generation, retries=0, terminal=True,
            message="存储路径或清理规则异常，请联系管理员修正后重试删除", error_type=type(exc).__name__))
        raise


@celery.task(name=PROCESS_TASK, bind=True, base=Task, max_retries=12, acks_late=True, reject_on_worker_lost=True)
def process_document_task(self, document_id, generation):
    try:
        return run_async(_run(document_id, generation, False))
    except RetryableDeletionError as exc:
        if self.request.retries >= self.max_retries:
            run_async(Document.filter(id=document_id, generation=generation, is_deleted=False).update(
                status=DocumentStatus.FAILED, error_message="文档操作锁不可用，请稍后重试"))
            raise
        raise self.retry(exc=exc, countdown=min(30, 2 ** min(self.request.retries + 1, 5)))


@celery.task(name=SWEEP_TASK, base=Task)
def sweep_document_jobs_task():
    async def sweep():
        await init_tortoise_orm()
        return {"recovered": await sweep_jobs()}
    return run_async(sweep())
