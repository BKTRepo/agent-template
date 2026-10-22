"""原 RAG 删除流程的当前模型适配：持久任务、严格锁、自动重试与巡检。"""
import asyncio
from datetime import datetime, timedelta, timezone
import uuid

from tortoise.transactions import in_transaction

from applications.knowledge_base.models.knowledge_base_model import Document
from applications.knowledge_base.services.job_control import (
    DocumentLease, ProcessingControl, DocumentCancelled,
    RetryableDeletionError, NonRetryableDeletionError,
)
from configure import PROJECT_CONFIG, LOGGER
from enums import DocumentStatus

PROCESS_TASK = "celery_scheduler.tasks.task_knowledge.process_document_task"
DELETE_TASK = "celery_scheduler.tasks.task_knowledge.delete_document_task"
SWEEP_TASK = "celery_scheduler.tasks.task_knowledge.sweep_document_jobs_task"


def _publish(task_name, args, *, task_id):
    from celery_scheduler.celery_worker import celery
    celery.send_task(task_name, args=args, task_id=task_id, retry=False,
                     queue="knowledge_delete" if task_name == DELETE_TASK else "knowledge_parse")


async def dispatch_jobs(jobs, *, publish=None):
    publish = publish or _publish
    submitted = []
    for document_id in dict.fromkeys(jobs):
        async with in_transaction() as conn:
            doc = await Document.filter(id=document_id).using_db(conn).select_for_update().first()
            if not doc:
                continue
            task_id, generation = uuid.uuid4().hex, doc.generation
            doc.task_id, doc.task_dispatched_at = task_id, datetime.now(timezone.utc)
            await doc.save(using_db=conn, update_fields=["task_id", "task_dispatched_at"])
            task_name = DELETE_TASK if doc.is_deleted else PROCESS_TASK
        try:
            await asyncio.to_thread(publish, task_name, [document_id, generation], task_id=task_id)
            submitted.append(document_id)
        except Exception:
            LOGGER.exception("知识库任务提交失败，保留数据库记录: {}", document_id)
            await Document.filter(id=document_id, generation=generation, task_id=task_id).update(
                status=DocumentStatus.DELETE_FAILED if doc.is_deleted else DocumentStatus.FAILED,
                deletion_retryable=False if doc.is_deleted else True,
                deletion_error_type="DispatchError" if doc.is_deleted else None,
                error_message="任务提交失败，记录已保留，请重试", task_dispatched_at=None)
    return submitted


async def deletion_progress(document_id, generation, *, retries, terminal=False, message="", error_type=None, delay=None):
    await Document.filter(id=document_id, generation=generation, is_deleted=True).update(
        status=DocumentStatus.DELETE_FAILED if terminal else DocumentStatus.DELETING,
        deletion_retry_count=retries, deletion_retryable=not terminal,
        deletion_error_type=error_type, error_message=message,
        next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=delay) if delay else None)


class DocumentJobRunner:
    def __init__(self, service=None, lease_factory=DocumentLease):
        if service is None:
            from .platform_service import KnowledgeService
            service = KnowledgeService()
        self.service, self.lease_factory = service, lease_factory

    async def run(self, document_id, generation, *, deleting):
        doc = await Document.get_or_none(id=document_id)
        if not doc or doc.generation != generation or doc.is_deleted != deleting:
            return {"status": "skipped", "reason": "missing_or_outdated"}
        if deleting and (doc.status == DocumentStatus.DELETE_FAILED or not doc.deletion_retryable):
            return {"status": "skipped", "reason": "manual_retry_required"}
        lease = self.lease_factory(document_id)
        await lease.acquire()  # 立即失败／重试，不占执行槽等待另一文档操作。
        try:
            doc = await Document.get_or_none(id=document_id)
            if not doc or doc.generation != generation or doc.is_deleted != deleting:
                return {"status": "skipped", "reason": "outdated_after_lock"}
            if deleting:
                # 同文档租约持有期间保护外部清理；清理期间也续期。
                heartbeat = asyncio.create_task(self._renew(lease))
                try:
                    await self.service._delete_document(doc, propagate=True, lease=lease)
                finally:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
                return {"status": "deleted"}
            if doc.status not in {DocumentStatus.PROCESSING, DocumentStatus.COMPLETED}:
                return {"status": "skipped", "reason": "not_processing"}
            if doc.status == DocumentStatus.PROCESSING:
                # 拿到严格租约后可接管前次崩溃残留；活着的旧执行者不可能持同一把锁。
                await Document.filter(id=document_id, generation=generation, is_deleted=False).update(processing_started_time=None)
                control = ProcessingControl(document_id, generation, lease)
                async with control.watching():
                    await self.service.pipeline._process(document_id, control=control)
                    await control.check()
            await lease.renew()
            try:
                await self.service.clean_retired_files(document_id)
            except OSError as exc:
                raise RetryableDeletionError("替换前旧文件暂时无法清理，稍后重试") from exc
            current = await Document.get_or_none(id=document_id)
            return {"status": current.status.value if current else "removed"}
        except DocumentCancelled:
            # 若因 Redis 租约失效而非用户删除取消，保留待恢复任务；不触碰新代次。
            return {"status": "cancelled"}
        finally:
            await lease.release()

    @staticmethod
    async def _renew(lease):
        while True:
            await asyncio.sleep(PROJECT_CONFIG.KNOWLEDGE_CANCEL_POLL_SECONDS)
            await lease.renew()


async def sweep_jobs(*, dispatch=None, locked=None):
    """Beat 巡检提交前崩溃／Worker 失联的持久记录；不重跑终态删除失败。"""
    dispatch = dispatch or dispatch_jobs
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=PROJECT_CONFIG.KNOWLEDGE_JOB_STALE_SECONDS)
    now, jobs = datetime.now(timezone.utc), []
    docs = await Document.filter(status__in=[DocumentStatus.PROCESSING, DocumentStatus.DELETING, DocumentStatus.COMPLETED]).all()
    for doc in docs:
        if doc.status == DocumentStatus.COMPLETED and not doc.cleanup_file_paths:
            continue
        if doc.is_deleted and not doc.deletion_retryable:
            await Document.filter(id=doc.id, generation=doc.generation).update(status=DocumentStatus.DELETE_FAILED)
            continue
        if doc.next_retry_at and doc.next_retry_at > now:
            continue
        activity = doc.processing_started_time or doc.task_dispatched_at
        if activity and activity > cutoff:
            continue
        if locked is None:
            lease = DocumentLease(doc.id)
            try:
                is_locked = await asyncio.to_thread(lease.client.exists, lease.key)
            except Exception:
                continue  # Redis 不可用，不能假定原 Worker 已经死亡。
        else:
            is_locked = await locked(doc.id)
        if is_locked:
            continue
        async with in_transaction() as conn:
            current = await Document.filter(id=doc.id).using_db(conn).select_for_update().first()
            if not current or current.generation != doc.generation or current.task_dispatched_at != doc.task_dispatched_at:
                continue
            if current.is_deleted and current.deletion_retry_count >= PROJECT_CONFIG.KNOWLEDGE_DELETE_MAX_RETRIES:
                current.status, current.deletion_retryable = DocumentStatus.DELETE_FAILED, False
                current.deletion_error_type = "RecoveryExhausted"
                current.error_message = "自动恢复次数已用完，请重试删除"
                await current.save(using_db=conn)
                continue
            if current.is_deleted:
                current.deletion_retry_count += 1
            current.processing_started_time = None
            current.task_dispatched_at = now  # 多个 Beat 并发时只允许一方领取。
            await current.save(using_db=conn)
            jobs.append(current.id)
    if jobs:
        await dispatch(jobs)
    return jobs
