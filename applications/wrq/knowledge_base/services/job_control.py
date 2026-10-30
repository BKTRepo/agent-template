"""适配原 RAG：严格 Redis 同文档租约、取消心跳、异常分类。"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import threading
import uuid

from applications.wrq.knowledge_base.models.knowledge_base_model import Document
from configure import CELERY_CONFIG, PROJECT_CONFIG, LOGGER
from enums import DocumentStatus


class RetryableDeletionError(RuntimeError):
    """锁等待、Redis／向量暂时不可用、文件占用，可定时重试。"""


class NonRetryableDeletionError(RuntimeError):
    """路径越界等永久错误，需要人工修正。"""


class DocumentCancelled(RuntimeError):
    pass


RELEASE = 'if redis.call("get",KEYS[1]) == ARGV[1] then return redis.call("del",KEYS[1]) end return 0'
RENEW = 'if redis.call("get",KEYS[1]) == ARGV[1] then return redis.call("pexpire",KEYS[1],ARGV[2]) end return 0'


class DocumentLease:
    """解析和删除共用一把锁；Redis 故障绝不降级放行。"""
    def __init__(self, document_id, client=None):
        if client is None:
            import redis
            client = redis.Redis.from_url(CELERY_CONFIG.CELERY_BROKER_URL,
                socket_connect_timeout=2, socket_timeout=2)
        self.client = client
        self.key = "knowledge:document:" + document_id
        self.token = uuid.uuid4().hex  # 每次执行独立，不能让相同 Celery ID 的重投递重入。
        self.ttl = PROJECT_CONFIG.KNOWLEDGE_LOCK_TTL_SECONDS * 1000

    async def acquire(self):
        try:
            acquired = await asyncio.to_thread(self.client.set, self.key, self.token, nx=True, px=self.ttl)
        except Exception as exc:
            raise RetryableDeletionError("无法确认文档操作锁，稍后重试") from exc
        if not acquired:
            raise RetryableDeletionError("等待此文档停止处理，其他文档不受影响")

    async def renew(self):
        try:
            result = await asyncio.to_thread(self.client.eval, RENEW, 1, self.key, self.token, self.ttl)
            if not result:
                raise DocumentCancelled("文档租约已失效，禁止继续写入")
        except DocumentCancelled:
            raise
        except Exception as exc:
            raise DocumentCancelled("文档租约无法续期，停止本次任务") from exc

    async def release(self):
        try:
            await asyncio.to_thread(self.client.eval, RELEASE, 1, self.key, self.token)
        except Exception:
            LOGGER.warning("文档租约释放失败，将由 TTL 回收")


class ProcessingControl:
    def __init__(self, document_id, generation, lease=None):
        self.document_id, self.generation, self.lease = document_id, generation, lease
        self.stop = threading.Event()

    async def check(self):
        if self.stop.is_set():
            raise DocumentCancelled("文档已移除、更新或失去操作租约")
        current = await Document.get_or_none(id=self.document_id)
        if not current or current.is_deleted or current.generation != self.generation:
            self.stop.set()
            raise DocumentCancelled("文档已移除或更新，停止旧任务")
        if self.lease:
            await self.lease.renew()

    async def watch(self):
        try:
            while True:
                await self.check()
                await Document.filter(id=self.document_id, generation=self.generation, is_deleted=False,
                                      status=DocumentStatus.PROCESSING).update(
                    processing_started_time=datetime.now(timezone.utc))
                await asyncio.sleep(PROJECT_CONFIG.KNOWLEDGE_CANCEL_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 供 Docling 的监督线程读取；监测失败也不能继续不受保护地写入。
            self.stop.set()

    @asynccontextmanager
    async def watching(self):
        task = asyncio.create_task(self.watch())
        try:
            yield self
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
