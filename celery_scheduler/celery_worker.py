# -*- coding: utf-8 -*-
import asyncio
import logging
import traceback
from abc import ABC
from datetime import datetime
from typing import Any, Dict, Optional

from celery import Celery, Task
from celery._state import _task_stack
from celery.signals import setup_logging, task_prerun, worker_process_init
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
    get_scheduler_value,
    init_tortoise_orm,
    reset_tortoise_orm_state,
)

_async_event_loop_pool = None

_SCAN_TASK_NAME = "celery_scheduler.tasks.task_dispatch.scan_and_dispatch_tasks"

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


def _get_task_id_from_request(request) -> Optional[Any]:
    """TaskCenterInfo 主键，来自 Celery 消息 properties.__task_id。"""
    return getattr(request, "properties", {}).get("__task_id", None)


async def _ensure_tortoise_then_create_task_record(
        celery_id: str,
        task_celery_node: str,
        celery_trace_id: str,
        task_id: Optional[Any],
):
    await init_tortoise_orm()
    await _create_task_record(
        celery_id=celery_id,
        task_celery_node=task_celery_node,
        celery_trace_id=celery_trace_id,
        task_id=task_id,
    )


async def _create_task_record(
        celery_id: str,
        task_celery_node: str,
        celery_trace_id: str,
        task_id: Optional[Any],
):
    from applications.task_center.models.task_center_model import TaskCenterInfo
    from applications.task_center.services.task_record_crud import TaskCenterRecordCrud
    from enums import TaskCenterScheduler, TaskCenterStatus

    task_name: Optional[str] = None
    task_kwargs: Dict[str, Any] = {}
    task_celery_scheduler: Optional[str] = None
    task_version: Optional[int] = None

    if task_id is not None:
        task_instance = await TaskCenterInfo.filter(id=task_id, state=0).first()
        if task_instance:
            task_name = getattr(task_instance, "task_name", None)
            task_kwargs = getattr(task_instance, "task_kwargs", None) or {}
            task_version = getattr(task_instance, "task_version", None) or 0
            scheduler = task_instance.task_celery_scheduler
            task_celery_scheduler = (
                TaskCenterScheduler(scheduler)
                if isinstance(scheduler, str)
                else scheduler
            )
            task_instance.task_celery_time = datetime.now()
            task_instance.task_celery_status = TaskCenterStatus.RUNNING
            await task_instance.save(update_fields=["task_celery_time", "task_celery_status"])

    data: Dict[str, Any] = {
        "task_id": task_id,
        "task_version": task_version,
        "task_name": task_name,
        "task_kwargs": task_kwargs,
        "celery_id": celery_id,
        "task_celery_node": task_celery_node,
        "celery_trace_id": celery_trace_id,
        "task_celery_status": TaskCenterStatus.RUNNING,
        "task_celery_scheduler": task_celery_scheduler,
        "celery_start_time": datetime.now(),
    }
    await TaskCenterRecordCrud().create_record(data)
    LOGGER.info(
        f"【Worker】创建执行记录成功: \n"
        f"任务ID: {task_id}\n"
        f"调度ID: {celery_id}\n"
        f"任务执行版本: {task_version}\n"
        f"任务调度节点: {task_celery_node}\n"
    )


async def _update_task_record_on_end(
        celery_id: str,
        success: bool,
        result_or_error: str,
        traceback_str: str = None,
):
    if not celery_id:
        return
    from applications.task_center.services.task_record_crud import TaskCenterRecordCrud
    from enums import TaskCenterStatus

    now = datetime.now()
    status_enum = TaskCenterStatus.SUCCESS if success else TaskCenterStatus.FAILURE
    summary = (result_or_error or "").strip() or ""
    data = {
        "task_celery_status": status_enum,
        "celery_end_time": now,
        "task_summary": summary,
        "task_error": None if success else (traceback_str or summary),
    }
    record_crud = TaskCenterRecordCrud()
    record = await record_crud.get_by_celery_id(celery_id=celery_id)
    if not record:
        LOGGER.error(f"【Worker】更新执行记录失败, 调度ID[{celery_id}]不存在")
        return
    if record.celery_start_time:
        start = record.celery_start_time
        if getattr(start, "tzinfo", None) is not None:
            start = start.replace(tzinfo=None)
        delta = now - start
        data["celery_duration"] = f"{delta.total_seconds():.2f}s"
    await record_crud.update_record_by_celery_id(celery_id=celery_id, data=data)

    if record.task_id:
        from applications.task_center.models.task_center_model import TaskCenterInfo
        task_info = await TaskCenterInfo.filter(id=record.task_id, state=0).first()
        if task_info:
            task_info.task_celery_status = status_enum
            update_fields = ["task_celery_status"]
            if get_scheduler_value(getattr(task_info, "task_celery_scheduler", None)) == "datetime":
                task_info.task_enabled = False
                update_fields.append("task_enabled")
            await task_info.save(update_fields=update_fields)

    LOGGER.info(
        f"【Worker】更新执行记录成功: \n"
        f"任务ID: {record.task_id}\n"
        f"调度ID: {celery_id}\n"
        f"任务调度节点: {record.task_celery_node}\n"
    )


@task_prerun.connect
def receiver_task_pre_run(task: Task, *args, **kwargs):
    task_id = _get_task_id_from_request(task.request)
    celery_id = task.request.id
    task_celery_node = (task.name or "").strip()
    try:
        if task_id is not None:
            try:
                h = getattr(task.request, "headers", None) or {}
                if isinstance(h, dict):
                    celery_trace_id_val = h.get("trace_id") or (h.get("headers") or {}).get("trace_id") or ""
                else:
                    celery_trace_id_val = ""
                get_async_event_loop_pool().run(
                    _ensure_tortoise_then_create_task_record(
                        task_id=task_id,
                        celery_id=celery_id,
                        task_celery_node=task_celery_node,
                        celery_trace_id=celery_trace_id_val,
                    )
                )
            except Exception as e:
                LOGGER.error(
                    f"【Worker】创建执行记录失败: \n"
                    f"任务ID: {task_id}\n"
                    f"调度ID: {celery_id}\n"
                    f"任务调度节点: {task_celery_node}\n"
                    f"错误类型: {type(e).__name__}\n"
                    f"错误描述: {e}\n\t"
                    f"错误回溯: {traceback.format_exc()}\n"
                )
    except Exception as e:
        LOGGER.error(
            f"【Worker】任务提交异常(task_prerun.connect): \n"
            f"任务ID: {task_id}\n"
            f"调度ID: {celery_id}\n"
            f"任务调度节点: {task_celery_node}\n"
            f"错误类型: {type(e).__name__}\n"
            f"错误描述: {e}\n"
            f"错误回溯: {traceback.format_exc()}\n"
        )


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
            task_center_task_id = options.pop("__task_id", None)
            headers = {
                "headers": celery_dispatch_trace_headers(),
                "__task_id": task_center_task_id,
            }
            options.update(headers)
            return super().send_task(name, args=args, kwargs=kwargs, **options)

    class ContextTask(Task, ABC):
        Request = TaskRequest

        def delay(self, *args, **kwargs):
            return self.apply_async(args, kwargs)

        def apply_async(
                self, args=None, kwargs=None, task_id=None, producer=None,
                link=None, link_error=None, shadow=None, **options
        ):
            # task_id 参数为 Celery 消息 ID（可选）；options.__task_id 为 TaskCenterInfo 主键
            task_center_task_id = options.get("__task_id", None)
            headers = {
                "headers": celery_dispatch_trace_headers(),
                "__task_id": task_center_task_id,
            }
            if options:
                options.update(headers)
            else:
                options = headers
            return super(ContextTask, self).apply_async(
                args, kwargs, task_id, producer, link, link_error, shadow, **options
            )

        def handle_task_record(self, success: bool, result_or_error: str, traceback_str: str = None):
            task_center_task_id = _get_task_id_from_request(self.request)
            if self.request.id and self.name != _SCAN_TASK_NAME and task_center_task_id is not None:
                try:
                    get_async_event_loop_pool().run(
                        _update_task_record_on_end(
                            celery_id=self.request.id,
                            success=success,
                            result_or_error=result_or_error or "",
                            traceback_str=traceback_str,
                        )
                    )
                except Exception as e:
                    LOGGER.error(
                        f"【Worker】更新执行记录异常: \n"
                        f"任务ID: {_get_task_id_from_request(self.request)}\n"
                        f"调度ID: {self.request.id}\n"
                        f"任务调度节点: {self.name}\n"
                        f"错误描述: {type(e).__name__}: {e}\n"
                        f"错误回溯: {traceback.format_exc()}\n"
                    )

        def on_success(self, retval, task_id, args, kwargs):
            celery_id = task_id
            task_center_task_id = _get_task_id_from_request(self.request)
            task_celery_node = self.name or ""

            # 解析任务执行结果
            if isinstance(retval, dict):
                success = retval.get("success", True) is not False
                if not success:
                    summary = str(retval.get("error") or retval)
                else:
                    summary = str(retval)
            else:
                success = True
                summary = str(retval) if retval is not None else ""

            if task_celery_node == _SCAN_TASK_NAME:
                if success and isinstance(retval, dict):
                    LOGGER.info(
                        f"【Worker】扫描完成, 按条件()分发任务: \n"
                        f"调度ID: {celery_id}\n"
                        f"任务调度节点: {_SCAN_TASK_NAME}\n"
                        f"扫描任务总数: {retval.get('scanned')}, 可调度数: {retval.get('dispatched')}, 被跳过数: {retval.get('skipped')}\n"
                        f"扫描描述: {retval.get('desc')}"
                    )
                else:
                    LOGGER.error(
                        f"【Worker】任务扫描失败: \n"
                        f"调度ID: {celery_id}\n"
                        f"任务调度节点: {_SCAN_TASK_NAME}\n"
                        f"错误描述: {summary}\n"
                    )
            elif success:
                LOGGER.info(
                    f"【Worker】任务执行成功: \n"
                    f"任务ID: {task_center_task_id}\n"
                    f"调度ID: {celery_id}\n"
                    f"任务调度节点: {task_celery_node}\n"
                )
            else:
                LOGGER.error(
                    f"【Worker】任务执行失败: \n"
                    f"任务ID: {task_center_task_id}\n"
                    f"调度ID: {celery_id}\n"
                    f"任务调度节点: {task_celery_node}\n"
                    f"错误描述: {summary}\n"
                )
            self.handle_task_record(success, summary)
            return super(ContextTask, self).on_success(retval, task_id, args, kwargs)

        def on_failure(self, exc, task_id, args, kwargs, einfo):
            celery_id = task_id
            task_center_task_id = _get_task_id_from_request(self.request)
            task_celery_node = self.name or ""
            if task_celery_node == _SCAN_TASK_NAME:
                LOGGER.error(
                    f"【Worker】任务扫描失败: \n"
                    f"调度ID: {celery_id}\n"
                    f"错误类型: {type(exc).__name__}\n"
                    f"错误描述: {exc}\n"
                    f"错误回溯: {traceback.format_exc()}\n"
                )
            else:
                LOGGER.error(
                    f"【Worker】任务执行失败: \n"
                    f"任务ID: {task_center_task_id}\n"
                    f"调度ID: {celery_id}\n"
                    f"任务调度节点: {task_celery_node}\n"
                    f"错误类型: {type(exc).__name__}\n"
                    f"错误描述: {exc}\n"
                    f"错误回溯: {traceback.format_exc()}\n"
                )
            self.handle_task_record(False, str(exc) if exc else "", getattr(einfo, "traceback", None) or "")
            return super(ContextTask, self).on_failure(exc, task_id, args, kwargs, einfo)

        def __call__(self, *args, **kwargs):
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

            _task_stack.push(self)
            self.push_request(args=args, kwargs=kwargs)
            try:
                if asyncio.iscoroutinefunction(self.run):
                    return get_async_event_loop_pool().run(self.run(*args, **kwargs))
                return self.run(*args, **kwargs)
            finally:
                self.pop_request()
                _task_stack.pop()

    _celery_: Celery = NewCelery("Worker", task_cls=ContextTask)
    _celery_.config_from_object(CELERY_CONFIG.CELERY_CONFIG)
    return _celery_


celery = create_celery()

# Worker: celery -A celery_scheduler.celery_worker worker -Q default -c 4 -l INFO
# Beat:   celery -A celery_scheduler.celery_worker beat -l INFO

if __name__ == "__main__":
    import sys

    celery.start(argv=sys.argv[1:])
