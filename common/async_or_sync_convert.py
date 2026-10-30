# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import asyncio as aio
import inspect
import sys
import threading
from typing import Any, Awaitable, Callable, Coroutine, Optional, Type, Union

AnyCallable = Callable[..., Any]
AnyException = Union[Exception, Type[Exception]]
AnyCoroutine = Coroutine[Any, Any, Any]

PY39_VERSION = sys.version_info[:2] >= (3, 9)


async def sync_to_async(func, *args, **kwargs):
    if PY39_VERSION:
        return await asyncio.to_thread(func, *args, **kwargs)
    pool = AsyncEventLoopContextIOPool.singleton
    if not pool:
        pool = AsyncEventLoopContextIOPool()
    return await pool.loop.run_in_executor(None, lambda: func(*args, **kwargs))


def async_to_sync(coroutine: Awaitable, *args, **kwargs):
    async def inner_async_function(*args, **kwargs):
        return await coroutine

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(inner_async_function(*args, **kwargs))
    loop.close()
    return result


class AsyncEventLoopContextIOPool:
    """
    Celery worker 中执行 async + Tortoise 的专用事件循环池。
    所有涉及 Tortoise 的协程必须在池线程的同一 event loop 中执行。
    """
    loop: aio.AbstractEventLoop
    loop_runner: threading.Thread
    singleton: Optional["AsyncEventLoopContextIOPool"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "AsyncEventLoopContextIOPool":
        if not isinstance(cls.singleton, cls):
            cls.singleton = super(AsyncEventLoopContextIOPool, cls).__new__(cls)
        return cls.singleton

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        try:
            aio.get_running_loop()
            raise SystemError("此线程中已存在一个正在运行的循环！")
        except RuntimeError:
            pass

        self.limit = 1
        self.loop = aio.new_event_loop()
        self.loop_runner = threading.Thread(
            target=self.loop.run_forever,
            name="celery-worker-async-loop",
            daemon=True,
        )
        self.loop_runner.start()
        aio.set_event_loop(self.loop)

        _done = threading.Event()

        def _set_loop_in_pool_thread():
            aio.set_event_loop(self.loop)
            _done.set()

        self.loop.call_soon_threadsafe(_set_loop_in_pool_thread)
        _done.wait(timeout=2.0)

    def run(self, task_function: Union[AnyCallable, AnyCoroutine], *args: Any, **kwargs: Any) -> Any:
        if inspect.iscoroutinefunction(task_function):
            task_function = task_function(*args, **kwargs)

        if callable(task_function) and not bool(
                inspect.iscoroutine(task_function) or aio.isfuture(task_function)
        ):
            task_function = aio.to_thread(task_function, *args, **kwargs)

        if not inspect.isawaitable(task_function):
            return task_function

        try:
            result: aio.Future = aio.run_coroutine_threadsafe(task_function, self.loop)
        except TypeError:
            return task_function

        if error := result.exception():
            raise error

        return self.run(result.result())

    @classmethod
    def run_in_pool(cls, task_function: Union[AnyCallable, AnyCoroutine], *args: Any, **kwargs: Any) -> Any:
        if not (worker_pool := cls.singleton):
            worker_pool = cls()
        return worker_pool.run(task_function, *args, **kwargs)

    @classmethod
    def reset_process_state(cls) -> None:
        cls.singleton = None

    async def shutdown(self) -> None:
        if self.loop.is_running():
            self.loop.stop()
            await self.loop.shutdown_asyncgens()

        closer = getattr(self.loop, "aclose", None)
        if not self.loop.is_closed() and callable(closer):
            await closer()

    def join(self) -> None:
        self.loop_runner.join()
