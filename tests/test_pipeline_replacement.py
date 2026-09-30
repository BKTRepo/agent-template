from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from applications.jiayueyang.services.rag_pipeline import RagPipelineService
from configure import PROJECT_CONFIG
from core.exceptions import ParameterException


@pytest.mark.asyncio
async def test_busy_previous_task_does_not_clear_cancel_flag(monkeypatch):
    service = SimpleNamespace(get_document_entry=AsyncMock(), save_document=AsyncMock())
    pipeline = RagPipelineService(service)
    monkeypatch.setattr('applications.jiayueyang.services.rag_pipeline._acquire_delete_job_lock', lambda *_: False)
    with pytest.raises(ParameterException):
        await pipeline._reserve_replacement_task({'id':'doc-test','status':'embedding','cancel_requested':False})
    service.save_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_replacement_reserves_same_token_before_dispatch(monkeypatch):
    service = SimpleNamespace(get_document_entry=AsyncMock(return_value={'status':'failed'}), save_document=AsyncMock())
    acquired=[]
    monkeypatch.setattr('applications.jiayueyang.services.rag_pipeline._acquire_delete_job_lock', lambda job, token: acquired.append((job,token)) or True)
    doc={'id':'doc-test','status':'embedding','cancel_requested':False}
    token=await RagPipelineService(service)._reserve_replacement_task(doc)
    assert acquired == [('doc-test',token)]
    assert doc['celery_task_id'] == token
    service.save_document.assert_awaited_once_with(doc, bypass_guard=True)


@pytest.mark.asyncio
async def test_submitted_rollback_embedding_state_reaches_archive_checks(monkeypatch, tmp_path):
    service=SimpleNamespace(get_document_entry=AsyncMock(return_value={'status':'embedding','celery_task_id':'rollback-1'}))
    pipeline=RagPipelineService(service);pipeline._execution_token='rollback-1'
    pipeline._update=AsyncMock()
    monkeypatch.setattr(PROJECT_CONFIG,'RAG_OUTPUT_DIR',str(tmp_path))
    result=await pipeline._run_rollback_inner('doc-test')
    assert result['error']=='prev 归档不完整'
    pipeline._update.assert_awaited_once()
    pipeline._execution_token='old-task'
    result=await pipeline._run_rollback_inner('doc-test')
    assert '不属于当前回滚任务' in result['error']
