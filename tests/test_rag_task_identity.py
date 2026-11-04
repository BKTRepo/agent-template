"""Verify real Celery task wrapper carries broker identity into the async pool."""
import pytest
from celery_scheduler import celery_worker
from celery_scheduler.celery_base import LOCAL_CONTEXT_VAR
from applications.knowledge_base.tasks.task_rag_pipeline import get_celery_execution_id


def test_repeated_pool_construction_keeps_async_resources_on_original_loop():
    import asyncio
    from common import AsyncEventLoopContextIOPool
    first = AsyncEventLoopContextIOPool()
    original_loop = first.loop

    async def create_waiter():
        return asyncio.get_running_loop().create_future()

    waiter = first.run(create_waiter())
    second = AsyncEventLoopContextIOPool()
    assert second.loop is original_loop

    async def consume_waiter():
        asyncio.get_running_loop().call_soon(waiter.set_result, 'same-loop')
        return await waiter

    assert second.run(consume_waiter()) == 'same-loop'


@pytest.mark.parametrize('asynchronous', [False, True])
def test_wrapper_preserves_execution_identity_and_retries(monkeypatch, asynchronous):
    monkeypatch.setattr(celery_worker, 'ensure_tortoise_orm_initialized', lambda: None)
    app = celery_worker.create_celery()
    if asynchronous:
        @app.task(name='itest.async.identity')
        async def task():
            return get_celery_execution_id()
    else:
        @app.task(name='itest.sync.identity', bind=True)
        def task(self):
            return self.request.id, self.request.retries, get_celery_execution_id()
    previous = LOCAL_CONTEXT_VAR.task_id
    task.push_request(id='reserved-retry-task', retries=3, headers={})
    try:
        result = task()
        assert result == ('reserved-retry-task' if asynchronous else ('reserved-retry-task', 3, 'reserved-retry-task'))
        assert task.request.id == 'reserved-retry-task'
        assert LOCAL_CONTEXT_VAR.task_id == previous
    finally:
        task.pop_request()
