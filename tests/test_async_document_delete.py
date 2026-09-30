"""删除改为 Worker 任务后，接口必须保留派发结果而非返回通用失败。"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from applications.jiayueyang.services.rag_service import RagDocumentService
from applications.jiayueyang.views.rag_view import delete_files


def test_deletion_cleans_standard_dirs_before_paths_saved(monkeypatch, tmp_path):
    from configure import PROJECT_CONFIG
    input_base = tmp_path / 'input'
    output_base = tmp_path / 'output'
    monkeypatch.setattr(PROJECT_CONFIG, 'RAG_INPUT_DIR', str(input_base))
    monkeypatch.setattr(PROJECT_CONFIG, 'RAG_OUTPUT_DIR', str(output_base))
    for base in (input_base, output_base):
        (base / 'doc-interrupted').mkdir(parents=True)
        (base / 'doc-interrupted' / 'artifact.txt').write_text('unfinished')
        (base / 'doc-other').mkdir()
    doc = {'id': 'doc-interrupted', 'input_path': '', 'output_path': ''}
    RagDocumentService._remove_input_dir(doc)
    RagDocumentService._remove_output_dirs(doc)
    for base in (input_base, output_base):
        assert not (base / 'doc-interrupted').exists()
        assert (base / 'doc-other').exists()


def test_deletion_rejects_standard_dir_escape(monkeypatch, tmp_path):
    from configure import PROJECT_CONFIG
    from applications.jiayueyang.services.rag_service import NonRetryableDeletionError
    input_base = tmp_path / 'input'
    output_base = tmp_path / 'output'
    monkeypatch.setattr(PROJECT_CONFIG, 'RAG_INPUT_DIR', str(input_base))
    monkeypatch.setattr(PROJECT_CONFIG, 'RAG_OUTPUT_DIR', str(output_base))
    outside = tmp_path / 'keep'
    outside.mkdir()
    for cleanup in (RagDocumentService._remove_input_dir, RagDocumentService._remove_output_dirs):
        with pytest.raises(NonRetryableDeletionError):
            cleanup({'id': '../keep', 'input_path': '', 'output_path': ''})
        assert outside.exists()


def test_document_deletion_uses_current_milvus_module(monkeypatch):
    from configure import PROJECT_CONFIG
    from applications.jiayueyang.rag import milvus_store
    deleted=[]
    monkeypatch.setattr(PROJECT_CONFIG,'VECTOR_BACKEND','milvus')
    monkeypatch.setattr(milvus_store,'delete_by_doc_id',lambda doc: deleted.append(doc) or 1)
    RagDocumentService._delete_vectors('doc-regression')
    assert deleted==['doc-regression']


@pytest.mark.asyncio
async def test_delete_endpoint_accepts_queued_contract():
    service = SimpleNamespace(
        delete_files_and_docs=AsyncMock(return_value={"queued": ["doc-1"], "failed": []}),
    )
    response = await delete_files(job_ids="doc-1", document_service=service)
    body = json.loads(response.body)
    assert body["code"] == "000000"
    assert body["data"] == {"queued": ["doc-1"], "failed": []}


@pytest.mark.asyncio
async def test_delete_dispatch_keeps_failures_and_backward_compatible_success(monkeypatch):
    from celery_scheduler.celery_worker import celery

    service = RagDocumentService()
    service.crud = SimpleNamespace(
        mark_deleting=AsyncMock(return_value=[
            SimpleNamespace(job_id="doc-ok"), SimpleNamespace(job_id="doc-failed"),
        ]),
        set_deleting_task_id=AsyncMock(return_value=True),
    )

    def dispatch(_task, *, kwargs):
        if kwargs["job_id"] == "doc-failed":
            raise ConnectionError("broker unavailable")
        return SimpleNamespace(id="delete-task-1")

    monkeypatch.setattr(celery, "send_task", dispatch)
    result = await service.delete_files_and_docs("doc-ok\ndoc-failed")
    assert result == {
        "queued": ["doc-ok"], "deleted": ["doc-ok"], "failed": ["doc-failed"],
    }
    service.crud.set_deleting_task_id.assert_awaited_once_with("doc-ok", "delete-task-1")


@pytest.mark.asyncio
async def test_delete_missing_document_is_successful_noop(monkeypatch):
    from celery_scheduler.celery_worker import celery

    service = RagDocumentService()
    service.crud = SimpleNamespace(mark_deleting=AsyncMock(return_value=[]))

    def unexpected_dispatch(*args, **kwargs):
        pytest.fail("不存在的文档不应派发删除任务")

    monkeypatch.setattr(celery, "send_task", unexpected_dispatch)
    result = await service.delete_files_and_docs("missing")
    assert result == {"queued": [], "deleted": [], "failed": []}
