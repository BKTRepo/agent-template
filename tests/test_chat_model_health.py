"""Redis 模型状态缓存、刷新并发与故障降级。"""
import asyncio
import json
import os
import time
import unittest
from unittest.mock import AsyncMock, patch

for key, value in {
    'AUTH_SECRET_KEY': 'isolated-chat-test-secret-' * 4,
    'DATABASE_HOST': '127.0.0.1', 'DATABASE_PORT': '3306',
    'DATABASE_USERNAME': 'test', 'DATABASE_NAME': 'test',
}.items():
    os.environ[key] = value

from applications.chat.services import model_health as module


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lock_sets = 0
    async def get(self, key):
        return self.values.get(key)
    async def set(self, key, value, *, nx=False, ex=None):
        if nx:
            self.lock_sets += 1
            if key in self.values:
                return False
        self.values[key] = value
        return True
    async def eval(self, script, n, key, token):
        if self.values.get(key) == token:
            del self.values[key]
    async def aclose(self):
        pass


class RedisModelHealthTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await module.close_health_cache()
        self.redis = FakeRedis()
        self.config = {'ANTHROPIC_BASE_URL': 'https://gateway.test',
                       'ANTHROPIC_API_KEY': 'secret', 'ANTHROPIC_MODEL': 'model-1'}
        self.models = patch.object(module, 'configured_model_ids', return_value=('deepseek',))
        self.environment = patch.object(module, 'model_environment', return_value=self.config)
        self.client = patch.object(module, '_get_redis', return_value=self.redis)
        self.models.start(); self.environment.start(); self.client.start()

    async def asyncTearDown(self):
        await module.close_health_cache()
        self.client.stop(); self.environment.stop(); self.models.stop()

    @staticmethod
    def sample(status='healthy', lifetime=60):
        return {'model': 'deepseek', 'status': status, 'latency_ms': 120, 'http_status': 200,
                'checked_at': '2026-11-10T00:00:00+00:00', 'fresh_until': time.time() + lifetime}

    async def test_miss_is_nonblocking_and_concurrent_requests_refresh_once(self):
        barrier = asyncio.Event()
        async def probe(model, config):
            await barrier.wait()
            return self.sample()
        with patch.object(module, 'probe', side_effect=probe) as mocked:
            results = await asyncio.gather(*(module.health() for _ in range(10)))
            self.assertTrue(all(row[0]['status'] == 'checking' for row in results))
            await asyncio.sleep(0)
            barrier.set()
            await asyncio.gather(*list(module._refreshing.values()))
            self.assertEqual(mocked.await_count, 1)
            self.assertEqual(self.redis.lock_sets, 1)
            # 模拟另一个进程无本地缓存，从 Redis 获取已有结果。
            module._local.clear()
            result = (await module.health())[0]
            self.assertEqual(result['status'], 'healthy')
            self.assertFalse(result['stale'])
            self.assertEqual(result['checked_at'], '2026-11-10T00:00:00+00:00')
            self.assertEqual(mocked.await_count, 1)
            self.assertEqual(await module.select_model(), 'deepseek')

    async def test_stale_status_is_marked_and_replaced_asynchronously(self):
        key = module._identity('deepseek', self.config)
        self.redis.values[key] = json.dumps(self.sample(lifetime=-10))
        with patch.object(module, 'probe', new=AsyncMock(return_value=self.sample(status='busy', lifetime=30))) as mocked:
            result = (await module.health())[0]
            self.assertEqual(result['status'], 'healthy')
            self.assertTrue(result['stale'])
            self.assertTrue(result['refreshing'])
            await asyncio.gather(*list(module._refreshing.values()))
            next_result = (await module.health())[0]
            self.assertEqual(next_result['status'], 'busy')
            self.assertFalse(next_result['stale'])
            self.assertIsNone(await module.select_model())
            self.assertEqual(mocked.await_count, 1)

    async def test_distributed_lock_prevents_a_second_probe(self):
        key = module._identity('deepseek', self.config)
        self.redis.values[key + ':lock'] = 'other-process'
        with patch.object(module, 'probe', new=AsyncMock(return_value=self.sample())) as mocked:
            result = (await module.health())[0]
            self.assertEqual(result['status'], 'checking')
            await asyncio.gather(*list(module._refreshing.values()))
            mocked.assert_not_awaited()
            self.assertEqual(self.redis.values[key + ':lock'], 'other-process')

    async def test_redis_failure_uses_local_cache_and_reuses_it(self):
        with patch.object(self.redis, 'get', new=AsyncMock(side_effect=ConnectionError('offline'))), \
             patch.object(module, 'probe', new=AsyncMock(return_value=self.sample())) as mocked:
            self.assertEqual((await module.health())[0]['status'], 'checking')
            await asyncio.gather(*list(module._refreshing.values()))
            self.assertEqual((await module.health())[0]['status'], 'healthy')
            self.assertEqual(mocked.await_count, 1)

    async def test_configuration_change_invalidates_previous_status(self):
        old = module._identity('deepseek', self.config)
        new = module._identity('deepseek', self.config | {'ANTHROPIC_MODEL': 'new-model'})
        self.assertNotEqual(old, new)
        self.assertNotIn('secret', old)

    async def test_uncached_auto_routing_uses_shared_default_model(self):
        with patch.object(module, 'configured_model_ids', return_value=('deepseek', 'glm51')), \
             patch.object(module, 'default_model', return_value='glm51'):
            self.assertEqual(await module.select_model(), 'glm51')

    async def test_statuses_have_different_freshness_windows(self):
        class Response:
            def __init__(self, code):
                self.status_code = code
                self.is_success = code == 200
        class Client:
            status_code = 200
            def __init__(self, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def post(self, *args, **kwargs):
                return Response(self.status_code)
        with patch.object(module.httpx, 'AsyncClient', Client), \
             patch.object(module.PROJECT_CONFIG, 'CHAT_MODEL_HEALTH_TTL_SECONDS', 60), \
             patch.object(module.PROJECT_CONFIG, 'CHAT_MODEL_HEALTH_FAILURE_TTL_SECONDS', 30):
            start = time.time()
            good = await module.probe('deepseek', self.config)
            Client.status_code = 429
            limited = await module.probe('deepseek', self.config)
        self.assertEqual((good['status'], limited['status']), ('healthy', 'busy'))
        self.assertGreaterEqual(good['fresh_until'] - start, 59)
        self.assertLess(limited['fresh_until'] - start, 32)

if __name__ == '__main__':
    unittest.main()
