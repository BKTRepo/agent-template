"""清空后异步清理旧文件；任务结束和统计完成前不删除文件。"""

import asyncio
import shutil
import socket

from applications.chat.models.chat_model import ChatArtifact, ChatArtifactCount, ChatCleanup, ChatMessage, ChatTask
from applications.chat.services.artifacts import artifact_root, count_artifact
from configure import LOGGER


async def process_cleanup(cleanup_id: int):
    cleanup = await ChatCleanup.get_or_none(id=cleanup_id)
    if not cleanup or cleanup.status == "completed":
        return
    tasks = ChatTask.filter(conversation_id=cleanup.conversation_id, generation=cleanup.generation)
    if await tasks.filter(status__in=["pending", "running", "cancelling", "recovering"]).exists():
        return
    try:
        artifacts = await ChatArtifact.filter(task__conversation_id=cleanup.conversation_id,
                                              task__generation=cleanup.generation)
        for artifact in artifacts:
            if artifact.count_status in ("pending", "failed"):
                await count_artifact(artifact.id)
        # 统计重试耗尽时保存失败原因，再删除文件，不能把无法识别的用例估算为 1。
        failed = await ChatArtifact.filter(task__conversation_id=cleanup.conversation_id,
            task__generation=cleanup.generation, count_status='needs_review')
        for item in failed:
            await ChatArtifactCount.get_or_create(artifact_id=item.id,
                defaults={'quantity': None, 'status': 'failed', 'error': item.count_error})
        if await ChatArtifact.filter(task__conversation_id=cleanup.conversation_id,
            task__generation=cleanup.generation).exclude(count_status__in=['counted', 'needs_review']).exists():
            # 文件尚在等待统计或重试。
            return
        root = artifact_root()
        target = (root / "conversations" / cleanup.conversation_id / str(cleanup.generation)).resolve()
        if not target.is_relative_to(root) or target == root:
            raise ValueError("清理目录越界")
        if target.exists():
            await asyncio.to_thread(shutil.rmtree, target)
        from applications.chat.services.attachments import remove_task_uploads
        for task in await tasks:
            if task.worker_host == socket.gethostname():
                await asyncio.to_thread(remove_task_uploads, task.id)
        await ChatMessage.filter(conversation_id=cleanup.conversation_id, generation=cleanup.generation).delete()
        await tasks.delete()
        cleanup.status = "completed"
        cleanup.error = None
        await cleanup.save(update_fields=["status", "error"])
    except Exception as exc:
        cleanup.retry_count += 1
        cleanup.status = "failed"
        cleanup.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        await cleanup.save(update_fields=["status", "retry_count", "error"])
        LOGGER.warning("悬浮窗旧产物清理失败: cleanup_id={}", cleanup.id)


async def cleanup_loop():
    last_history_scan = 0.0
    while True:
        try:
            loop = asyncio.get_running_loop()
            if loop.time() - last_history_scan >= 300 or not last_history_scan:
                from applications.chat.services.history_files import resync_histories
                await resync_histories()
                last_history_scan = loop.time()
            from applications.chat.services.execution import recover_stale_tasks, start_task
            for task in await ChatTask.filter(status='pending').order_by('id').limit(100):
                start_task(task.id)
            await recover_stale_tasks()
            from applications.chat.services.attachments import cleanup_uploads
            await cleanup_uploads()
            pending = await ChatArtifact.filter(count_status__in=["pending", "failed"],
                                                task__status="success").order_by("id").limit(100)
            for artifact in pending:
                await count_artifact(artifact.id)
            for record in await ChatCleanup.filter(status__in=["pending", "failed"]).order_by("id").limit(100):
                await process_cleanup(record.id)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("悬浮窗清理任务扫描失败")
        await asyncio.sleep(60)
