# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any, Awaitable, Coroutine, Dict, Iterator, Optional, Tuple, Union

from tortoise import Tortoise, connections
from tortoise.exceptions import DBConnectionError

from configure import PROJECT_CONFIG, LOGGER

_tortoise_orm_initialized = False
_init_async_lock: Optional[asyncio.Lock] = None


def reset_tortoise_orm_state() -> None:
    global _tortoise_orm_initialized
    _tortoise_orm_initialized = False


def run_async(func: Union[Coroutine, Awaitable]) -> Any:
    from common import AsyncEventLoopContextIOPool
    return AsyncEventLoopContextIOPool.run_in_pool(func)


async def init_tortoise_orm() -> None:
    global _tortoise_orm_initialized, _init_async_lock

    from celery_scheduler import ensure_project_root_on_path

    ensure_project_root_on_path()

    if _init_async_lock is None:
        _init_async_lock = asyncio.Lock()

    async with _init_async_lock:
        if _tortoise_orm_initialized:
            try:
                conn = connections.get("default")
                if conn and hasattr(conn, "_pool") and conn._pool:
                    try:
                        await conn.execute_query("SELECT 1")
                        return
                    except Exception:
                        LOGGER.warning("【Base】数据库连接已断开，将重新初始化")
                        _tortoise_orm_initialized = False
                        try:
                            await Tortoise.close_connections()
                        except Exception:
                            pass
                else:
                    _tortoise_orm_initialized = False
            except Exception as e:
                LOGGER.warning(f"【Base】数据库连接检查失败，将重新初始化: {str(e)}")
                _tortoise_orm_initialized = False
                try:
                    await Tortoise.close_connections()
                except Exception:
                    pass

        config: Dict[str, Any] = {
            "connections": PROJECT_CONFIG.DATABASE_CONNECTIONS,
            "apps": {
                "models": {
                    "models": PROJECT_CONFIG.APPLICATIONS_MODELS,
                    "default_connection": "default",
                }
            },
            "use_tz": False,
            "timezone": "Asia/Shanghai",
        }

        try:
            await Tortoise.init(config=config)
            _tortoise_orm_initialized = True
            LOGGER.info("【Base】Tortoise ORM 数据库连接初始化成功")
        except DBConnectionError as e:
            LOGGER.error(f"【Base】数据库连接失败: {str(e)}")
            raise RuntimeError(f"【Base】数据库连接失败, 请检查主机地址是否可达: {str(e)}")
        except Exception as e:
            LOGGER.error(f"【Base】数据库初始化失败: {str(e)}")
            raise


def ensure_tortoise_orm_initialized() -> None:
    from common import AsyncEventLoopContextIOPool

    try:
        AsyncEventLoopContextIOPool.run_in_pool(init_tortoise_orm())
    except Exception as e:
        LOGGER.error(f"【Base】确保数据库初始化失败: {str(e)}")
        raise


def get_span_id_for_log() -> str:
    from common.request_context import get_span_id as _get

    sid = _get()
    if sid and sid != "-":
        return sid
    return getattr(LOCAL_CONTEXT_VAR, "span_id", None) or ""


class LocalContextVar:
    __slots__ = ("_storage",)

    def __init__(self) -> None:
        object.__setattr__(self, "_storage", ContextVar("local_storage"))

    def __iter__(self) -> Iterator[Tuple[int, Any]]:
        return iter(self._storage.get({}).items())

    def __release_local__(self) -> None:
        self._storage.set({})

    def __getattr__(self, name: str) -> Any:
        values = self._storage.get({})
        try:
            return values[name]
        except KeyError:
            return None

    def __setattr__(self, name: str, value: Any) -> None:
        values = self._storage.get({}).copy()
        values[name] = value
        self._storage.set(values)

    def __delattr__(self, name: str) -> None:
        values = self._storage.get({}).copy()
        try:
            del values[name]
            self._storage.set(values)
        except KeyError:
            ...


LOCAL_CONTEXT_VAR = LocalContextVar()
