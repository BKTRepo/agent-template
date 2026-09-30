import asyncio
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from celery_scheduler.celery_base import get_celery_execution_id
from celery_scheduler.celery_worker import celery


def test_async_task_keeps_real_message_id_across_event_loop_thread(monkeypatch):
    def bridge(coroutine):
        context=copy_context()
        with ThreadPoolExecutor(1) as pool:
            return pool.submit(context.run, asyncio.run, coroutine).result()
    monkeypatch.setattr('celery_scheduler.celery_worker.ensure_tortoise_orm_initialized',lambda: None)
    monkeypatch.setattr('celery_scheduler.celery_worker.get_async_event_loop_pool',lambda: SimpleNamespace(run=bridge))
    @celery.task(name='tests.regression_async_execution_id')
    async def task():
        return get_celery_execution_id()
    for identifier in ['message-1','message-2']:
        task.push_request(id=identifier)
        try:
            assert task() == identifier
        finally:
            task.pop_request()
    assert get_celery_execution_id() is None
