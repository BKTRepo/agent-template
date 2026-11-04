# -*- coding: utf-8 -*-
import asyncio
import logging
import traceback
from abc import ABC
from typing import Any, Dict, Optional

from celery import Celery, Task
from celery._state import _task_stack
from celery.signals import setup_logging, worker_process_init
from celery.worker.request import Request

from common import AsyncEventLoopContextIOPool
from common.request_context import (
    _extract_celery_trace_fields,
    celery_dispatch_trace_headers,
    enter_celery_span,
)
from configure import CELERY_CONFIG, LOGGER
from configure.logging_config import InterceptHandler
from .celery_base import (
    LOCAL_CONTEXT_VAR,
    ensure_tortoise_orm_initialized,
    reset_tortoise_orm_state,
)

_async_event_loop_pool = None


# Celery 框架 logger：仅 WARNING+，屏蔽 trace 的 Task ... succeeded in ... 等 INFO
_CELERY_QUIET_LOGGERS = (
    "celery",
    "celery.worker",
    "celery.app",
    "celery.app.trace",
    "celery.pool",
    "kombu",
    "billiard",
    "redis",
    "redbeat",
    "amqp",
    "logging",
)


@worker_process_init.connect
def _reset_async_pool_and_tortoise_after_fork(**kwargs):
    global _async_event_loop_pool
    _async_event_loop_pool = None
    AsyncEventLoopContextIOPool.reset_process_state()
    reset_tortoise_orm_state()
    from configure.logging_config import loguru_logging

    loguru_logging()
    LOGGER.debug("【Worker】worker_process_init.connect: 已重置异步池、Tortoise 与日志 Sink")


def get_async_event_loop_pool():
    global _async_event_loop_pool
    if _async_event_loop_pool is None:
        _async_event_loop_pool = AsyncEventLoopContextIOPool()
    return _async_event_loop_pool


@setup_logging.connect
def setup_loggers(*args, **kwargs):
    """统一 Celery 日志：框架 trace 等仅 WARNING+，避免 Task succeeded in ... 刷屏。"""
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)
    for name in _CELERY_QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


class TaskRequest(Request):
    def __init__(self, *args, **kwargs):
        super(TaskRequest, self).__init__(*args, **kwargs)
        self._restore_trace_context()

    def _restore_trace_context(self):
        trace_id, span_id, parent_span_id = _extract_celery_trace_fields(self.request_dict)
        enter_celery_span(trace_id, parent_span_id, span_id)


def create_celery():
    class NewCelery(Celery):
        def send_task(self, name, args=None, kwargs=None, **options):
            options["headers"] = {**(options.get("headers") or {}), **celery_dispatch_trace_headers()}
            return super().send_task(name, args=args, kwargs=kwargs, **options)

    class ContextTask(Task, ABC):
        Request = TaskRequest

        def delay(self, *args, **kwargs):
            return self.apply_async(args, kwargs)

        def apply_async(
                self, args=None, kwargs=None, task_id=None, producer=None,
                link=None, link_error=None, shadow=None, **options
        ):
            options["headers"] = {**(options.get("headers") or {}), **celery_dispatch_trace_headers()}
            return super(ContextTask, self).apply_async(
                args, kwargs, task_id, producer, link, link_error, shadow, **options
            )

        def on_success(self, retval, task_id, args, kwargs):
            LOGGER.info("Celery 任务完成: {} ({})", self.name, task_id)
            return super().on_success(retval, task_id, args, kwargs)

        def on_failure(self, exc, task_id, args, kwargs, einfo):
            LOGGER.error("Celery 任务失败: {} ({}) {}", self.name, task_id, exc)
            return super().on_failure(exc, task_id, args, kwargs, einfo)

        def __call__(self, *args, **kwargs):
            request_context = self.request.__dict__.copy()
            try:
                hdr = self.request.headers or {}
                if isinstance(hdr, dict):
                    trace_id, span_id, parent_span_id = _extract_celery_trace_fields(hdr)
                else:
                    trace_id, span_id, parent_span_id = "", "", ""
                if not trace_id:
                    trace_id = getattr(LOCAL_CONTEXT_VAR, "trace_id", None) or ""
                enter_celery_span(trace_id, parent_span_id, span_id)
            except Exception:
                trace_id = getattr(LOCAL_CONTEXT_VAR, "trace_id", None) or ""
                enter_celery_span(trace_id, "", "")

            ensure_tortoise_orm_initialized()

            previous_task_id = LOCAL_CONTEXT_VAR.task_id
            LOCAL_CONTEXT_VAR.task_id = request_context.get("id")
            _task_stack.push(self)
            # 保留 Celery 的原始编号及重试信息；ContextVar 将编号带入异步池线程。
            self.push_request(**{**request_context, "args": args, "kwargs": kwargs})
            try:
                if asyncio.iscoroutinefunction(self.run):
                    return get_async_event_loop_pool().run(self.run(*args, **kwargs))
                return self.run(*args, **kwargs)
            finally:
                self.pop_request()
                _task_stack.pop()
                LOCAL_CONTEXT_VAR.task_id = previous_task_id

    _celery_: Celery = NewCelery("Worker", task_cls=ContextTask)
    _celery_.config_from_object(CELERY_CONFIG.CELERY_CONFIG)
    return _celery_


celery = create_celery()

# Worker: celery -A celery_scheduler.celery_worker worker -Q default -c 4 -l INFO
# Beat:   celery -A celery_scheduler.celery_worker beat -l INFO

if __name__ == "__main__":
    import sys

    celery.start(argv=sys.argv[1:])
