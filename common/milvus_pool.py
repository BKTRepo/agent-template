# -*- coding: utf-8 -*-
"""Thread-safe bounded pool for synchronous pymilvus clients."""

import atexit
import os
import queue
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Tuple, Type

from pymilvus import MilvusClient


class MilvusClientPool:
    """Lazily creates, reuses, and bounds independent Milvus clients.

    Each client must own a unique pymilvus connection alias. A borrowed client
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
        self._lock = threading.Lock()
        self._created = 0
        self._closed = False

    @property
    def created(self) -> int:
        with self._lock:
            return self._created

    def acquire(self) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError("Milvus client pool is closed")
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass

        should_create = False
        with self._lock:
            if self._created < self._max_size:
                self._created += 1
                should_create = True

        if should_create:
            try:
                return self._factory()
            except Exception:
                with self._lock:
                    self._created -= 1
                raise

        try:
            return self._idle.get(timeout=self._acquire_timeout)
        except queue.Empty as exc:
            raise TimeoutError(
                f"Timed out waiting {self._acquire_timeout:g}s for a Milvus connection"
            ) from exc

    def release(self, client: Any, *, broken: bool = False) -> None:
        with self._lock:
            if not broken and not self._closed:
                try:
                    self._idle.put_nowait(client)
                    return
                except queue.Full:
                    pass
        self._discard(client)

    def _discard(self, client: Any) -> None:
        try:
            client.close()
        finally:
            with self._lock:
                self._created = max(0, self._created - 1)

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
                # Prevent pymilvus from reusing its URI-derived global alias.
                "alias": f"milvus-pool-{os.getpid()}-{uuid.uuid4().hex}",
            }
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
