# -*- coding: utf-8 -*-
"""Thread-safe bounded pool for synchronous pymilvus clients."""

import atexit
import logging
import os
import queue
import threading
import time
import uuid
from contextlib import contextmanager
from importlib.metadata import version
from typing import Any, Callable, Dict, Iterator, Tuple, Type

from pymilvus import MilvusClient

_PYMILVUS_MAJOR_VERSION = int(version("pymilvus").split(".", 1)[0])
_LOGGER = logging.getLogger(__name__)


class MilvusClientPool:
    """Lazily creates, reuses, and bounds independent Milvus clients.

    Each client must own an independent pymilvus connection. A borrowed client
    is used by only one thread at a time; returning it makes it available for
    the next request. Clients involved in failed operations are discarded so
    a later acquisition reconnects cleanly.
    """

    def __init__(
        self,
        factory: Callable[[], Any],
        *,
        max_size: int,
        acquire_timeout: float,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        if acquire_timeout <= 0:
            raise ValueError("acquire_timeout must be positive")
        self._factory = factory
        self._max_size = max_size
        self._acquire_timeout = acquire_timeout
        self._idle: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=max_size)
        self._lock = threading.Condition()
        self._created = 0
        self._closed = False

    @property
    def created(self) -> int:
        with self._lock:
            return self._created

    def acquire(self) -> Any:
        deadline = time.monotonic() + self._acquire_timeout
        with self._lock:
            while True:
                if self._closed:
                    raise RuntimeError("Milvus client pool is closed")
                try:
                    return self._idle.get_nowait()
                except queue.Empty:
                    pass
                if self._created < self._max_size:
                    self._created += 1
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out waiting {self._acquire_timeout:g}s for a Milvus connection"
                    )
                # A discarded connection frees capacity without adding an idle
                # client. Waiting on the queue alone would miss that event.
                self._lock.wait(remaining)

        try:
            client = self._factory()
        except Exception:
            with self._lock:
                self._created -= 1
                self._lock.notify_all()
            raise
        with self._lock:
            if not self._closed:
                return client
        self._discard(client)
        raise RuntimeError("Milvus client pool is closed")

    def release(self, client: Any, *, broken: bool = False) -> None:
        with self._lock:
            if not broken and not self._closed:
                try:
                    self._idle.put_nowait(client)
                    self._lock.notify()
                    return
                except queue.Full:
                    pass
        self._discard(client)

    def _discard(self, client: Any) -> None:
        try:
            client.close()
        except Exception:
            # Cleanup failure must not mask the original RPC error or prevent
            # the read wrapper from attempting its one permitted retry.
            _LOGGER.warning("Failed to close a discarded Milvus client", exc_info=True)
        finally:
            with self._lock:
                self._created = max(0, self._created - 1)
                self._lock.notify_all()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        client = self.acquire()
        try:
            yield client
        except Exception:
            self.release(client, broken=True)
            raise
        else:
            self.release(client)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._lock.notify_all()
        while True:
            try:
                client = self._idle.get_nowait()
            except queue.Empty:
                break
            self._discard(client)


_PoolKey = Tuple[int, str, str, str, str, int, float, Type[Any]]
_POOLS: Dict[_PoolKey, MilvusClientPool] = {}
_POOLS_LOCK = threading.Lock()


def get_milvus_client_pool(
    *,
    uri: str,
    user: str = "",
    password: str = "",
    token: str = "",
    max_size: int = 8,
    acquire_timeout: float = 30.0,
    client_cls: Type[Any] = MilvusClient,
) -> MilvusClientPool:
    """Return the process-local shared pool for one Milvus endpoint/config."""
    key: _PoolKey = (
        os.getpid(), uri, user, password, token,
        int(max_size), float(acquire_timeout), client_cls,
    )
    with _POOLS_LOCK:
        pool = _POOLS.get(key)
        if pool is not None:
            return pool

        def factory() -> Any:
            kwargs: Dict[str, Any] = {
                "uri": uri,
            }
            if _PYMILVUS_MAJOR_VERSION >= 3:
                # 3.x shares handlers by endpoint/auth; an alias no longer
                # creates an independent channel. Dedicated connections are
                # also closed immediately when a broken client is discarded.
                kwargs["dedicated"] = True
            else:
                # 2.x honours an explicit unique alias in create_connection.
                kwargs["alias"] = f"milvus-pool-{os.getpid()}-{uuid.uuid4().hex}"
            if user:
                kwargs["user"] = user
            if password:
                kwargs["password"] = password
            if token:
                kwargs["token"] = token
            return client_cls(**kwargs)

        pool = MilvusClientPool(
            factory,
            max_size=int(max_size),
            acquire_timeout=float(acquire_timeout),
        )
        _POOLS[key] = pool
        return pool


def close_all_milvus_pools() -> None:
    """Close all idle clients owned by the current process."""
    pid = os.getpid()
    with _POOLS_LOCK:
        keys = [key for key in _POOLS if key[0] == pid]
        pools = [_POOLS.pop(key) for key in keys]
    for pool in pools:
        pool.close()


atexit.register(close_all_milvus_pools)
