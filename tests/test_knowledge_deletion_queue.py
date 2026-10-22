"""迁移源 RAG 删除语义：队列、严格锁、自动重试、取消和崩溃补偿。"""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import threading
import time

import pytest

from applications.knowledge_base.models.knowledge_base_model import Document
from applications.knowledge_base.services.document_jobs import DocumentJobRunner, dispatch_jobs, sweep_jobs, DELETE_TASK, PROCESS_TASK
from applications.knowledge_base.services.job_control import DocumentLease, ProcessingControl, DocumentCancelled, RetryableDeletionError, NonRetryableDeletionError
from configure import PROJECT_CONFIG
from enums import DocumentStatus
from test_platform_knowledge import kb_setup, FORM, save
from test_backend_boundaries import two_documents


class Lease:
    def __init__(self, doc_id): self.doc_id, self.released = doc_id, False
    async def acquire(self): pass
    async def renew(self): pass
    async def release(self): self.released = True


async def pending_delete(kb_setup):
    client, owner, _, service, index = kb_setup
    kb, keep, target = await two_documents(client, owner)
    target.is_deleted, target.status = True, DocumentStatus.DELETING
    target.generation += 1
    await target.save()
    return kb, keep, target


def test_routes_keep_delete_and_sweep_separate_from_parsing():
    from celery_scheduler.celery_worker import celery
    for task in [DELETE_TASK, "celery_scheduler.tasks.task_knowledge.sweep_document_jobs_task"]:
        assert celery.amqp.router.route({}, task)["queue"].name == "knowledge_delete"
    assert celery.amqp.router.route({}, PROCESS_TASK)["queue"].name == "knowledge_parse"


@pytest.mark.asyncio
async def test_dispatch_uses_only_document_id_generation_and_no_web_fallback(kb_setup, monkeypatch):
    from applications.knowledge_base.views.platform_view import schedule
    _, _, target = await pending_delete(kb_setup)
    calls = []
    def publish(name, args, **kwargs): calls.append((name, args, kwargs))
    assert await dispatch_jobs([target.id], publish=publish) == [target.id]
    assert calls[0][0:2] == (DELETE_TASK, [target.id, target.generation])
    await target.refresh_from_db()
    assert target.task_id == calls[0][2]["task_id"] and target.task_dispatched_at
    monkeypatch.setattr(PROJECT_CONFIG, "KNOWLEDGE_TASK_MODE", "celery")
    monkeypatch.setattr("applications.knowledge_base.services.document_jobs.dispatch_jobs", AsyncMock())
    background = SimpleNamespace(add_task=Mock())
    await schedule(background, kb_setup[3], [target.id])
    background.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_broker_failure_preserves_record_and_explicit_failure(kb_setup):
    _, _, target = await pending_delete(kb_setup)
    def unavailable(*args, **kwargs): raise ConnectionError("broker offline")
    assert await dispatch_jobs([target.id], publish=unavailable) == []
    await target.refresh_from_db()
    assert target.status == DocumentStatus.DELETE_FAILED and Path(target.file_path).exists()
    assert target.deletion_error_type == "DispatchError"


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["busy", "offline"])
async def test_strict_redis_lock_never_degrades_to_unprotected_cleanup(problem):
    client = SimpleNamespace(set=Mock(return_value=False))
    if problem == "offline": client.set.side_effect = ConnectionError("offline")
    with pytest.raises(RetryableDeletionError):
        await DocumentLease("doc", client).acquire()


@pytest.mark.asyncio
async def test_lock_renewal_detects_ownership_loss_and_release_is_token_checked():
    client = SimpleNamespace(set=Mock(return_value=True), eval=Mock(return_value=0))
    lease = DocumentLease("doc", client)
    await lease.acquire()
    with pytest.raises(DocumentCancelled): await lease.renew()
    await lease.release()
    assert client.eval.call_args.args[-1] == lease.token


@pytest.mark.asyncio
async def test_worker_cleans_old_artifacts_and_original_before_removing_sql(kb_setup, tmp_path, monkeypatch):
    _, _, target = await pending_delete(kb_setup)
    monkeypatch.setattr(PROJECT_CONFIG, "RAG_OUTPUT_DIR", str(tmp_path / "parsed"))
    artifact = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR) / "doc-artifact"
    artifact.mkdir(parents=True); (artifact / "image.png").write_bytes(b"image")
    old = Path(target.file_path).with_name("old.md"); old.write_bytes(b"old")
    target.artifact_paths, target.cleanup_file_paths = [str(artifact)], [str(old)]
    await target.save()
    result = await DocumentJobRunner(kb_setup[3], Lease).run(target.id, target.generation, deleting=True)
    assert result["status"] == "deleted" and not artifact.exists() and not old.exists()
    assert not Path(target.file_path).exists() and not await Document.filter(id=target.id).exists()


@pytest.mark.asyncio
async def test_permanent_path_error_does_not_remove_sql_or_external_file(kb_setup, tmp_path):
    _, _, target = await pending_delete(kb_setup)
    external = tmp_path / "outside.md"; external.write_bytes(b"keep")
    target.file_path = str(external); await target.save()
    with pytest.raises(NonRetryableDeletionError):
        await DocumentJobRunner(kb_setup[3], Lease).run(target.id, target.generation, deleting=True)
    assert external.exists() and await Document.filter(id=target.id).exists()


@pytest.mark.asyncio
async def test_stale_generation_message_cannot_delete_retried_or_new_task(kb_setup):
    _, _, target = await pending_delete(kb_setup)
    runner = DocumentJobRunner(kb_setup[3], lambda doc_id: (_ for _ in ()).throw(AssertionError("should not lock")))
    assert (await runner.run(target.id, target.generation - 1, deleting=True))["status"] == "skipped"
    assert Path(target.file_path).exists()


@pytest.mark.parametrize("retries,permanent,terminal", [(0, False, False), (11, False, False), (12, False, True), (0, True, True)])
def test_celery_retry_is_scheduled_not_blocking_and_exhaustion_is_visible(monkeypatch, retries, permanent, terminal):
    from celery.exceptions import Retry
    from celery_scheduler.tasks import task_knowledge as module
    error = NonRetryableDeletionError("path") if permanent else RetryableDeletionError("offline")
    monkeypatch.setattr(module, "_run", AsyncMock(side_effect=error))
    monkeypatch.setattr(module, "run_async", asyncio.run)
    progress = AsyncMock()
    monkeypatch.setattr(module, "deletion_progress", progress)
    monkeypatch.setattr(module.Document, "get_or_none", AsyncMock(return_value=SimpleNamespace(generation=2, deletion_retry_count=0)))
    retry = Mock(side_effect=Retry())
    monkeypatch.setattr(module.delete_document_task, "retry", retry)
    module.delete_document_task.push_request(id="delete-test", retries=retries)
    try:
        with pytest.raises((Retry, RetryableDeletionError, NonRetryableDeletionError)):
            module.delete_document_task.run("doc", 2)
    finally:
        module.delete_document_task.pop_request()
    assert progress.await_args.kwargs.get("terminal", False) is terminal
    if terminal: retry.assert_not_called()
    else: assert retry.call_args.kwargs["countdown"] == min(30, 2 ** min(retries + 1, 5))


@pytest.mark.asyncio
@pytest.mark.parametrize("locked,future,terminal,expected", [(False,False,False,True), (True,False,False,False),
    (False,True,False,False), (False,False,True,False)])
async def test_beat_recovers_only_dead_pending_deletes(kb_setup, locked, future, terminal, expected):
    _, _, target = await pending_delete(kb_setup)
    target.task_dispatched_at = datetime.now(timezone.utc) - timedelta(hours=1)
    target.status = DocumentStatus.DELETE_FAILED if terminal else DocumentStatus.DELETING
    target.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=1) if future else None
    await target.save()
    dispatch = AsyncMock()
    result = await sweep_jobs(dispatch=dispatch, locked=AsyncMock(return_value=locked))
    assert (target.id in result) is expected
    if expected: dispatch.assert_awaited_once_with([target.id])
    else: dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_beat_recovery_limit_becomes_delete_failed(kb_setup):
    _, _, target = await pending_delete(kb_setup)
    target.deletion_retry_count = 12; await target.save()
    await sweep_jobs(dispatch=AsyncMock(), locked=AsyncMock(return_value=False))
    await target.refresh_from_db()
    assert target.status == DocumentStatus.DELETE_FAILED and not target.deletion_retryable


@pytest.mark.asyncio
async def test_database_delete_request_sets_cross_process_cancel_signal(kb_setup):
    client, owner, _, _, _ = kb_setup
    kb = (await save(client, owner)).json()["data"]
    doc = await Document.get(id=kb["documents"][0]["id"])
    control = ProcessingControl(doc.id, doc.generation)
    await Document.filter(id=doc.id).update(is_deleted=True, generation=doc.generation + 1)
    with pytest.raises(DocumentCancelled): await control.check()
    assert control.stop.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_task", [False, True])
async def test_native_pdf_cancel_reaps_owned_process_before_return(monkeypatch, tmp_path, cancel_task):
    import psutil
    from common import docling_native
    from pdf_worker_probe import blocking_chunk
    monkeypatch.setattr(docling_native, "_process_chunk_in_process", blocking_chunk)
    monkeypatch.setattr(PROJECT_CONFIG, "RAG_OUTPUT_DIR", str(tmp_path))
    stop = threading.Event()
    conversion = asyncio.create_task(docling_native.convert_pdfs_to_bundles(
        [("one.pdf", b"a")], ["one"], should_cancel=stop.is_set))
    deadline = time.monotonic() + 25
    while not list(tmp_path.glob("worker-*.pid")) and time.monotonic() < deadline:
        await asyncio.sleep(.1)
    markers = list(tmp_path.glob("worker-*.pid"))
    try:
        assert markers, "worker did not start"
        pids = [int(p.read_text()) for p in markers]
        if cancel_task:
            conversion.cancel()
            with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(conversion, 10)
        else:
            stop.set()
            results = await asyncio.wait_for(conversion, 10)
            assert isinstance(results[0], docling_native.ConversionCancelledError)
        assert not any(psutil.pid_exists(pid) for pid in pids)
    finally:
        stop.set()
        await asyncio.gather(conversion, return_exceptions=True)


@pytest.mark.asyncio
async def test_normal_document_parser_can_be_cancelled_without_killing_worker(tmp_path):
    import psutil
    from applications.knowledge_base.services.cancellable_parser import parse_in_process
    from pdf_worker_probe import blocking_loader
    marker = tmp_path / "parser.pid"
    stop = threading.Event()
    task = asyncio.create_task(parse_in_process(str(marker), "txt", stop, worker=blocking_loader))
    deadline = time.monotonic() + 25
    while not marker.exists() and time.monotonic() < deadline: await asyncio.sleep(.1)
    try:
        assert marker.exists()
        pid = int(marker.read_text()); stop.set()
        with pytest.raises(DocumentCancelled): await asyncio.wait_for(task, 10)
        assert not psutil.pid_exists(pid)
    finally:
        stop.set()
        await asyncio.gather(task, return_exceptions=True)
