"""模型健康状态共享缓存；过期后异步刷新，Redis 故障时降级到进程内缓存。"""
import asyncio
import hashlib
import json
import math
import time
import uuid
from datetime import datetime, timezone

import httpx
import redis.asyncio as redis

from applications.chat.services.execution import model_environment
from configure import PROJECT_CONFIG
from services.model_gateway import configured_model_ids, default_model

# 数据保留一小时供刷新期间展示；是否可用于路由由 fresh_until 决定。
_RETAIN_SECONDS = 3600
_LOCK_SECONDS = 20
_REDIS_RETRY_SECONDS = 5
_RELEASE_LOCK = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) end return 0"
_local = {}
_refreshing = {}
_client = None
_client_loop = None
_redis_down_until = 0.0


def _get_redis():
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        url = PROJECT_CONFIG.REDIS_URL or PROJECT_CONFIG.build_redis_url(db=0)
        _client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.3,
                                      socket_timeout=0.3, retry_on_timeout=False)
        _client_loop = loop
    return _client


def _identity(model, config):
    # 配置变化后不能继续使用旧服务或旧凭证的健康结果；不保存凭证明文。
    value = '\0'.join((config['ANTHROPIC_BASE_URL'], config['ANTHROPIC_MODEL'],
                       config.get('ANTHROPIC_API_KEY', ''), config.get('ANTHROPIC_AUTH_TOKEN', '')))
    digest = hashlib.sha256(value.encode()).hexdigest()[:20]
    return f'chat:model-health:v1:{model}:{digest}'


def _unconfigured(model):
    return {'model': model, 'status': 'unconfigured', 'latency_ms': None, 'http_status': None,
            'checked_at': None, 'stale': False, 'refreshing': False}


def _checking(model):
    return {'model': model, 'status': 'checking', 'latency_ms': None, 'http_status': None,
            'checked_at': None, 'stale': True, 'refreshing': True}


def _public(sample, *, stale, refreshing):
    return {key: sample.get(key) for key in ('model', 'status', 'latency_ms', 'http_status', 'checked_at')} | {
        'stale': stale, 'refreshing': refreshing,
    }


def _valid(sample, model):
    return (isinstance(sample, dict) and sample.get('model') == model
            and sample.get('status') in {'healthy', 'busy', 'unavailable'}
            and isinstance(sample.get('fresh_until'), (int, float))
            and math.isfinite(sample['fresh_until'])
            and (sample['status'] != 'healthy' or
                 (isinstance(sample.get('latency_ms'), (int, float))
                  and math.isfinite(sample['latency_ms']) and sample['latency_ms'] >= 0)))


async def _read(key, model):
    global _redis_down_until
    sample = None
    if time.monotonic() >= _redis_down_until:
        try:
            raw = await _get_redis().get(key)
            if raw:
                candidate = json.loads(raw)
                if _valid(candidate, model):
                    sample = candidate
                    _local[key] = sample
        except Exception:
            _redis_down_until = time.monotonic() + _REDIS_RETRY_SECONDS
    if sample is None:
        sample = _local.get(key)
    if not _valid(sample, model):
        return None
    # 限制进程内降级缓存的最长保留时间，不能无限返回陈旧状态。
    if sample.get('fresh_until', 0) < time.time() - _RETAIN_SECONDS:
        _local.pop(key, None)
        return None
    return sample


async def probe(model, config):
    base = config['ANTHROPIC_BASE_URL'].rstrip('/')
    url = base + ('/messages' if base.endswith('/v1') else '/v1/messages')
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            headers = {'anthropic-version': '2023-06-01'}
            if config.get('ANTHROPIC_AUTH_TOKEN'):
                headers['Authorization'] = 'Bearer ' + config['ANTHROPIC_AUTH_TOKEN']
            elif config.get('ANTHROPIC_API_KEY'):
                headers['x-api-key'] = config['ANTHROPIC_API_KEY']
            response = await client.post(url, headers=headers, json={'model': config['ANTHROPIC_MODEL'], 'max_tokens': 32,
                'messages': [{'role': 'user', 'content': 'Hi'}]})
        status = 'healthy' if response.is_success else 'busy' if response.status_code == 429 else 'unavailable'
        sample = {'model': model, 'status': status, 'latency_ms': round((time.monotonic() - started) * 1000),
                  'http_status': response.status_code}
    except httpx.HTTPError:
        sample = {'model': model, 'status': 'unavailable', 'latency_ms': None, 'http_status': None}
    now = time.time()
    ttl = (PROJECT_CONFIG.CHAT_MODEL_HEALTH_TTL_SECONDS if sample['status'] == 'healthy'
           else PROJECT_CONFIG.CHAT_MODEL_HEALTH_FAILURE_TTL_SECONDS)
    sample['checked_at'] = datetime.fromtimestamp(now, timezone.utc).isoformat()
    sample['fresh_until'] = now + ttl
    return sample

async def _refresh(key, model, config):
    global _redis_down_until
    client = None
    token = uuid.uuid4().hex
    locked = False
    try:
        if time.monotonic() >= _redis_down_until:
            try:
                client = _get_redis()
                locked = bool(await client.set(key + ':lock', token, nx=True, ex=_LOCK_SECONDS))
                if not locked:
                    return
                # 双重检查：另一个进程可能刚刚刷新完毕。
                raw = await client.get(key)
                existing = json.loads(raw) if raw else None
                if _valid(existing, model) and existing['fresh_until'] > time.time():
                    _local[key] = existing
                    return
            except Exception:
                _redis_down_until = time.monotonic() + _REDIS_RETRY_SECONDS
                client = None
        sample = await probe(model, config)
        _local[key] = sample
        if client is not None and locked:
            try:
                await client.set(key, json.dumps(sample, ensure_ascii=False), ex=_RETAIN_SECONDS)
            except Exception:
                _redis_down_until = time.monotonic() + _REDIS_RETRY_SECONDS
    finally:
        if client is not None and locked:
            try:
                await client.eval(_RELEASE_LOCK, 1, key + ':lock', token)
            except Exception:
                pass


def _schedule(key, model, config):
    existing = _refreshing.get(key)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(_refresh(key, model, config), name=f'model-health-{model}')
    _refreshing[key] = task
    def finished(done):
        if _refreshing.get(key) is done:
            _refreshing.pop(key, None)
        if not done.cancelled():
            done.exception()  # 消费异常；下次请求会重新触发探测。
    task.add_done_callback(finished)


async def _status(model, *, refresh):
    try:
        config = model_environment(model)
    except RuntimeError:
        return _unconfigured(model)
    key = _identity(model, config)
    sample = await _read(key, model)
    if sample and sample['fresh_until'] > time.time():
        return _public(sample, stale=False, refreshing=False)
    if refresh:
        _schedule(key, model, config)
    if sample:
        return _public(sample, stale=True, refreshing=refresh)
    return _checking(model)


async def health():
    return await asyncio.gather(*(_status(model, refresh=True) for model in configured_model_ids()))


async def select_model():
    samples = await asyncio.gather(*(_status(model, refresh=False) for model in configured_model_ids()))
    if not samples:
        return None
    available = [item for item in samples if not item['stale'] and item['status'] == 'healthy']
    if available:
        return min(available, key=lambda item: item['latency_ms'])['model']
    unknown = [item for item in samples if item['status'] == 'checking' or item['stale']]
    if unknown:
        preferred = default_model()
        return next((item['model'] for item in unknown if item['model'] == preferred), unknown[0]['model'])
    if any(item['status'] in {'busy', 'unavailable'} for item in samples):
        return None
    return default_model()


async def close_health_cache():
    global _client, _client_loop, _redis_down_until
    tasks = list(_refreshing.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _refreshing.clear()
    if _client is not None:
        await _client.aclose()
    _client = None
    _client_loop = None
    _redis_down_until = 0.0
    _local.clear()
