"""单进程内同一文档的解析/清理互斥；不阻塞其他文档，不冒充分布式锁。"""
import asyncio
from weakref import WeakValueDictionary


_locks = WeakValueDictionary()


def document_lock(document_id):
    key = (id(asyncio.get_running_loop()), document_id)
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock
