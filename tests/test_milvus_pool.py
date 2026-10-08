import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from common import milvus_pool as module
from common.milvus_pool import MilvusClientPool


class Client:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False

    def close(self):
        self.closed = True


@pytest.mark.parametrize("major", [2, 3])
def test_sdk_specific_connections_are_independent_options(monkeypatch, major):
    monkeypatch.setattr(module, "_PYMILVUS_MAJOR_VERSION", major)
    monkeypatch.setattr(module, "_POOLS", {})
    pool = module.get_milvus_client_pool(uri="http://localhost:19530", max_size=2, client_cls=Client)
    first, second = pool.acquire(), pool.acquire()
    try:
        if major >= 3:
            assert first.kwargs["dedicated"] is second.kwargs["dedicated"] is True
            assert "alias" not in first.kwargs
        else:
            assert first.kwargs["alias"] != second.kwargs["alias"]
            assert "dedicated" not in first.kwargs
        pool.release(first, broken=True)
        replacement = pool.acquire()
        assert replacement is not first and first.closed and not second.closed
        pool.release(replacement)
    finally:
        pool.release(second)
        pool.close()


def test_healthy_client_is_reused_but_broken_client_is_discarded():
    pool = MilvusClientPool(Client, max_size=1, acquire_timeout=1)
    with pool.connection() as first:
        pass
    with pytest.raises(ValueError, match="closed channel"):
        with pool.connection() as second:
            assert first is second
            raise ValueError("closed channel")
    assert first.closed and pool.created == 0
    with pool.connection() as replacement:
        assert replacement is not first
    pool.close()
    assert replacement.closed and pool.created == 0


def test_waiter_can_create_replacement_when_broken_client_frees_capacity(monkeypatch):
    pool = MilvusClientPool(Client, max_size=1, acquire_timeout=2)
    borrowed = pool.acquire()
    waiting = threading.Event()
    original_wait = pool._lock.wait

    def wait(timeout):
        waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(pool._lock, "wait", wait)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(pool.acquire)
        assert waiting.wait(1)
        pool.release(borrowed, broken=True)
        replacement = future.result(timeout=1)
    assert replacement is not borrowed and borrowed.closed
    pool.release(replacement)
    pool.close()


def test_pool_close_wakes_waiter_and_closes_borrowed_client_on_return(monkeypatch):
    pool = MilvusClientPool(Client, max_size=1, acquire_timeout=2)
    borrowed = pool.acquire()
    waiting = threading.Event()
    original_wait = pool._lock.wait

    def wait(timeout):
        waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(pool._lock, "wait", wait)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(pool.acquire)
        assert waiting.wait(1)
        pool.close()
        with pytest.raises(RuntimeError, match="closed"):
            future.result(timeout=1)
    pool.release(borrowed)
    assert borrowed.closed and pool.created == 0


def test_failed_factory_returns_capacity():
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("connect failed")
        return Client()

    pool = MilvusClientPool(factory, max_size=1, acquire_timeout=1)
    with pytest.raises(ValueError, match="connect failed"):
        pool.acquire()
    assert pool.created == 0
    with pool.connection():
        assert pool.created == 1
    pool.close()


def test_discard_cleanup_error_does_not_mask_rpc_failure():
    class BadClose(Client):
        def close(self):
            raise RuntimeError("close failed")

    pool = MilvusClientPool(BadClose, max_size=1, acquire_timeout=1)
    with pytest.raises(ValueError, match="closed channel"):
        with pool.connection():
            raise ValueError("closed channel")
    assert pool.created == 0
    pool.close()


def test_pool_timeout_does_not_exceed_capacity():
    pool = MilvusClientPool(Client, max_size=1, acquire_timeout=0.02)
    borrowed = pool.acquire()
    with pytest.raises(TimeoutError):
        pool.acquire()
    assert pool.created == 1
    pool.release(borrowed)
    pool.close()


def test_client_created_during_shutdown_is_closed():
    started, finish = threading.Event(), threading.Event()
    created = []

    def factory():
        started.set()
        assert finish.wait(1)
        created.append(Client())
        return created[-1]

    pool = MilvusClientPool(factory, max_size=1, acquire_timeout=1)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(pool.acquire)
        assert started.wait(1)
        pool.close()
        finish.set()
        with pytest.raises(RuntimeError, match="closed"):
            future.result(timeout=1)
    assert created[0].closed and pool.created == 0
