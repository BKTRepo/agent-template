"""短期保存已注销的 JWT 指纹，直到其自然过期。"""
import hashlib
import math
import time

import redis.asyncio as redis

from configure import PROJECT_CONFIG


def _key(token: str) -> str:
    return 'auth:revoked:' + hashlib.sha256(token.encode()).hexdigest()


async def is_revoked(token: str) -> bool:
    client = redis.from_url(PROJECT_CONFIG.REDIS_URL or PROJECT_CONFIG.build_redis_url(db=0), decode_responses=True)
    try:
        return bool(await client.exists(_key(token)))
    finally:
        await client.aclose()


async def revoke(token: str, expires_at: float) -> None:
    client = redis.from_url(PROJECT_CONFIG.REDIS_URL or PROJECT_CONFIG.build_redis_url(db=0), decode_responses=True)
    try:
        await client.set(_key(token), '1', ex=max(1, math.ceil(expires_at - time.time())))
    finally:
        await client.aclose()
