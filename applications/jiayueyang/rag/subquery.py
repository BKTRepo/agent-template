# -*- coding: utf-8 -*-
"""复合问题分解。

分解是检索增强而不是主链路的硬依赖：模型输出不完整、超时或解析失败时，
先尝试一次受限重试，仍失败再走确定性规则兜底；失败结果不进入稳定缓存。
"""
import asyncio
import hashlib
import json
import re
import time as _time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from configure import LOGGER, PROJECT_CONFIG
from applications.jiayueyang.rag.llm import LLMTruncatedError, chat_completion

_DECOMPOSE_SYSTEM_PROMPT = """你是检索查询分析助手。判断用户问题是否为复合问题，即同时涉及多个相互独立的信息面。
单一主题输出 is_compound=false、sub_queries=[]；复合问题拆成 2~4 个自包含的单面查询。
每个子查询保留原问题中的专有名词、字段号、代码值，不改写不翻译。
严格只输出 JSON：{"is_compound": true/false, "sub_queries": ["..."]}。"""

@dataclass(frozen=True)
class DecomposeResult:
    sub_queries: List[str] = field(default_factory=list)
    status: str = "single"  # single | compound | fallback | failed
    method: str = "none"  # llm | rule | none
    failure_reason: Optional[str] = None
    retry_count: int = 0

    def __iter__(self):
        return iter(self.sub_queries)

    def __len__(self):
        return len(self.sub_queries)

@dataclass(frozen=True)
class _CacheEntry:
    result: DecomposeResult
    expires_at: float

_STABLE_CACHE: Dict[str, _CacheEntry] = {}
_FALLBACK_CACHE: Dict[str, _CacheEntry] = {}
_CACHE_MAX = 512
_DECOMPOSE_TIMEOUT_S = 15.0

def _cache_key(query: str) -> str:
    return hashlib.md5(query.encode("utf-8")).hexdigest()[:16]

def _cache_get(query: str) -> Optional[DecomposeResult]:
    key = _cache_key(query)
    now = _time.time()
    for cache in (_STABLE_CACHE, _FALLBACK_CACHE):
        entry = cache.get(key)
        if entry is None:
            continue
        if entry.expires_at > now:
            return entry.result
        cache.pop(key, None)
    return None

def _cache_set(query: str, result: DecomposeResult) -> None:
    if result.status == "failed":
        return
    cache = _STABLE_CACHE if result.method == "llm" else _FALLBACK_CACHE
    ttl = 3600.0 if cache is _STABLE_CACHE else float(getattr(PROJECT_CONFIG, "SUBQUERY_FALLBACK_CACHE_TTL", 300))
    if len(cache) >= _CACHE_MAX:
        oldest = min(cache, key=lambda k: cache[k].expires_at)
        cache.pop(oldest, None)
    cache[_cache_key(query)] = _CacheEntry(result=result, expires_at=_time.time() + ttl)

def clear_decompose_cache() -> None:
    _STABLE_CACHE.clear()
    _FALLBACK_CACHE.clear()

def _parse_decompose_result(raw: str, max_count: int) -> List[str]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start:end + 1])
        except Exception:
            return []
    if not isinstance(data, dict) or not data.get("is_compound"):
        return []
    result: List[str] = []
    for value in data.get("sub_queries") or []:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value and value not in result:
            result.append(value[:int(getattr(PROJECT_CONFIG, "SUBQUERY_MAX_LENGTH", 80))])
        if len(result) >= max_count:
            break
    return result

def _rule_fallback(query: str, max_count: int) -> List[str]:
    """模型不可用时保守切分，保留业务主体，避免产生裸数字子查询。"""
    q = (query or "").strip()
    if not q:
        return []
    pieces = [p.strip(" ，,；;。") for p in re.split(r"(?:分别|以及|同时|并且|还有|和|与|及)", q) if p.strip()]
    if len(pieces) < 2:
        pieces = [p.strip(" ，,；;。") for p in re.split(r"[?？;；]", q) if p.strip()]
    if len(pieces) < 2:
        return []
    result: List[str] = []
    for piece in pieces[:max_count]:
        if len(re.sub(r"[\W_]", "", piece, flags=re.UNICODE)) < 4:
            continue
        value = piece[:int(getattr(PROJECT_CONFIG, "SUBQUERY_MAX_LENGTH", 80))]
        if value and value not in result:
            result.append(value)
    return result if len(result) >= 2 else []

async def _call_decompose(q: str, max_tokens: int) -> str:
    return await asyncio.wait_for(
        chat_completion(
            messages=q,
            system_prompt=_DECOMPOSE_SYSTEM_PROMPT,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=max_tokens,
        ),
        timeout=_DECOMPOSE_TIMEOUT_S,
    )

async def decompose_query(query: str) -> DecomposeResult:
    q = (query or "").strip()
    if not q or not PROJECT_CONFIG.SUBQUERY_DECOMPOSE_ENABLED:
        return DecomposeResult()
    cached = _cache_get(q)
    if cached is not None:
        LOGGER.debug("子查询分解缓存命中: %s → %s", q[:50], len(cached.sub_queries))
        return cached
    max_tokens = int(getattr(PROJECT_CONFIG, "SUBQUERY_MAX_TOKENS", 500))
    retry_enabled = bool(getattr(PROJECT_CONFIG, "SUBQUERY_TRUNCATION_RETRY_ENABLED", True))
    retry_count = 0
    failure_reason: Optional[str] = None
    raw = ""
    for attempt in range(2 if retry_enabled else 1):
        try:
            raw = await _call_decompose(q, max_tokens)
            subs = _parse_decompose_result(raw if isinstance(raw, str) else "", PROJECT_CONFIG.SUBQUERY_MAX_COUNT)
            if subs:
                result = DecomposeResult(subs, "compound", "llm", retry_count=retry_count)
                _cache_set(q, result)
                return result
            try:
                parsed = json.loads((raw or "").strip().strip("`").strip())
                if isinstance(parsed, dict) and parsed.get("is_compound") is False:
                    result = DecomposeResult([], "single", "llm", retry_count=retry_count)
                    _cache_set(q, result)
                    return result
            except Exception:
                pass
            failure_reason = "invalid_json"
        except LLMTruncatedError:
            failure_reason = "truncated"
        except asyncio.TimeoutError:
            failure_reason = "timeout"
            break
        except Exception as exc:
            failure_reason = f"exception:{type(exc).__name__}"
            LOGGER.warning("子查询分解失败: %s, %s", q[:50], exc)
            break
        if attempt == 0 and retry_enabled:
            retry_count = 1
            max_tokens = min(max_tokens * 2, 1200)
    if bool(getattr(PROJECT_CONFIG, "SUBQUERY_RULE_FALLBACK_ENABLED", True)):
        fallback = _rule_fallback(q, PROJECT_CONFIG.SUBQUERY_MAX_COUNT)
        if fallback:
            result = DecomposeResult(fallback, "fallback", "rule", failure_reason, retry_count)
            _cache_set(q, result)
            return result
    return DecomposeResult([], "failed", "none", failure_reason, retry_count)
