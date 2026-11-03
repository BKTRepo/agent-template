# -*- coding: utf-8 -*-
"""向量嵌入 — 实现移植自 LightRAG, 使用 openai.AsyncOpenAI 与 tenacity 重试, 并做基于字符数的安全截断。"""

import asyncio
import base64
import json
import random
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from tenacity.stop import stop_base
from tenacity.wait import wait_base

from configure import LOGGER, PROJECT_CONFIG

# 抑制 openai SDK 产生的告警
warnings.filterwarnings("ignore", module="openai")


def _clean_text(text: str) -> str:
    """清洗用于嵌入的文本 — 折叠重复的无语义字符。"""
    # 折叠连续的圆点、竖线、空格、连字符 (表格排版残留)
    text = re.sub(r"\.{10,}", "...", text)
    text = re.sub(r"\|{5,}", " | ", text)
    text = re.sub(r" {10,}", " ", text)
    text = re.sub(r"\-{10,}", "---", text)
    return text


def _safe_truncate(text: str) -> Tuple[str, bool]:
    """清洗并截断文本 — 防止超长/异常分块导致 API 返回 400。

    字符上限取 ``EMBEDDING_MAX_CHARS_PER_TEXT``（需覆盖最大分块长度,
    否则分块尾部不参与向量化）。

    :return: (处理后文本, 是否发生截断)
    """
    text = _clean_text(text)
    limit = PROJECT_CONFIG.EMBEDDING_MAX_CHARS_PER_TEXT
    if len(text) > limit:
        return text[:limit], True
    return text, False


# ==================== OpenAI 兼容客户端 (对应 LightRAG 的 create_openai_async_client) ====================

# 进程级共享客户端: httpx 连接池复用, 避免逐批次新建客户端造成 socket 激增
_shared_client: Optional[Any] = None


def _get_client() -> Any:
    """获取共享的 AsyncOpenAI 客户端（首次调用时延迟创建）。

    连接池配置说明:
    - max_keepalive_connections: 保持连接的池大小, 匹配 EMBEDDING_MAX_CONCURRENT
      避免高并发下频繁 TCP 握手
    - max_connections: 硬上限, 设为 keepalive 的 2 倍以应对瞬时突发
    - trust_env=False: 忽略系统代理变量, 避免代理延迟波动
    """
    global _shared_client
    if _shared_client is None:
        # 延迟导入: 避免在模块加载时引入 openai 重依赖
        import httpx
        from openai import AsyncOpenAI

        pool_size = PROJECT_CONFIG.EMBEDDING_MAX_CONCURRENT
        http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_keepalive_connections=pool_size,
                max_connections=pool_size * 2,
            ),
            trust_env=False,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

        kwargs: Dict[str, Any] = {}
        kwargs["base_url"] = PROJECT_CONFIG.EMBEDDING_BINDING_HOST
        kwargs["http_client"] = http_client
        api_key = PROJECT_CONFIG.EMBEDDING_BINDING_API_KEY
        kwargs["api_key"] = api_key if (api_key and api_key != "not-needed") else "none"
        # max_retries=0: 禁用 SDK 内建的秒级短退避重试 — 限流 (429) 时短退避会放大重试风暴,
        # 重试统一交由 _embed_batch 外层 tenacity 的长退避 (4~60s) 处理
        kwargs["max_retries"] = 0
        _shared_client = AsyncOpenAI(**kwargs)
    return _shared_client


def _is_retryable(exc: BaseException) -> bool:
    """判定异常是否为可重试的瞬态故障 (限流/连接失败/超时/5xx); 400/401 等硬错误直接抛出不重试。"""
    # 延迟导入: 保持模块轻加载设计
    from openai import APIConnectionError, InternalServerError, RateLimitError

    # APITimeoutError 是 APIConnectionError 的子类, 一并覆盖
    return isinstance(exc, (APIConnectionError, RateLimitError, InternalServerError))


def _reset_shared_client_on_connection_error(exc: BaseException) -> None:
    """连接级失败时丢弃共享客户端, 下次重试重建连接池, 避免复用半开 socket。"""
    global _shared_client
    from openai import APIConnectionError

    if isinstance(exc, APIConnectionError) and _shared_client is not None:
        stale, _shared_client = _shared_client, None
        try:
            asyncio.ensure_future(stale.close())
        except Exception:
            # 关闭失败交由 GC 回收, 不影响主重试流程
            pass


# ==================== 429 限流感知的重试策略 ====================

def _is_rate_limited(exc: Optional[BaseException]) -> bool:
    """是否为 429 限流错误（供应商 TPM/RPM 配额耗尽）。"""
    if exc is None:
        return False
    from openai import RateLimitError  # 延迟导入

    return isinstance(exc, RateLimitError)


def _retry_after_seconds(exc: BaseException) -> Optional[float]:
    """解析服务端 Retry-After 响应头（秒）; 上限 120s 防异常值, 取不到返回 None。"""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        raw = response.headers.get("retry-after")
    except Exception:
        return None
    if not raw:
        return None
    try:
        return min(float(raw), 120.0)
    except (TypeError, ValueError):
        return None


class _EmbedWait(wait_base):
    """按异常类型分流的退避等待策略。

    429 限流: TPM 是滚动一分钟窗口, 同时失败的多个批次若按相同时间表
    同步重试（原 4→8→16→32s 指数退避无抖动）, 会成群反复撞进刚恢复
    的窗口（thundering herd）, 永远救不回来——故限流等待优先遵循
    Retry-After, 否则用 20~60s **随机**等待把各批重试时刻错开到宽带上。
    其他瞬态故障（连接失败/5xx）保持指数退避。
    quick 模式（查询路径）缩短限流等待, 避免交互式聊天挂死数分钟。
    """

    def __init__(self, quick: bool = False) -> None:
        self._quick = quick
        self._exponential = wait_exponential(
            multiplier=1, min=2 if quick else 4, max=15 if quick else 60
        )

    def __call__(self, retry_state) -> float:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if _is_rate_limited(exc):
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None:
                return retry_after + random.uniform(0, 5)
            if self._quick:
                return random.uniform(5, 15)
            return random.uniform(20, 60)
        return self._exponential(retry_state)


class _EmbedStop(stop_base):
    """按异常类型分流的重试次数策略。

    限流批次最多 10 次尝试（退避 20~60s, 可覆盖多个 TPM 窗口周期,
    单批最坏耗时仍在任务时限内）; 其他瞬态故障 5 次快速失败。
    quick 模式（查询路径）统一 3 次——查询失败应快速反馈给用户,
    不应在限流窗口里排队数分钟。
    """

    def __init__(self, quick: bool = False) -> None:
        if quick:
            self._normal = stop_after_attempt(3)
            self._rate_limited = stop_after_attempt(3)
        else:
            self._normal = stop_after_attempt(5)
            self._rate_limited = stop_after_attempt(10)

    def __call__(self, retry_state) -> bool:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        policy = self._rate_limited if _is_rate_limited(exc) else self._normal
        return policy(retry_state)


# ==================== 核心嵌入调用 (移植自 LightRAG 的 openai_embed) ====================

async def _embed_batch_call(
        texts: List[str],
        semaphore: asyncio.Semaphore,
        trunc_counter: Optional[List[int]] = None,
) -> np.ndarray:
    """单批次嵌入调用的实际执行体（重试策略由外层 tenacity 装饰器决定）。

    :param trunc_counter: 可选的截断计数器 ``[n]``: 本批被截断的文本数
        累加进去（单线程事件循环内累加, 无 await 切入, 竞态安全）。
    """
    async with semaphore:
        client = _get_client()
        cleaned = [_safe_truncate(t) for t in texts]
        if trunc_counter is not None:
            trunc_counter[0] += sum(1 for _, was_truncated in cleaned if was_truncated)
        params: Dict[str, Any] = {
            "model": PROJECT_CONFIG.EMBEDDING_MODEL,
            "input": [t for t, _ in cleaned],
        }

        # encoding_format: 与 LightRAG 的 EMBEDDING_USE_BASE64 处理方式保持一致
        params["encoding_format"] = "base64" if PROJECT_CONFIG.EMBEDDING_USE_BASE64 else "float"

        if PROJECT_CONFIG.EMBEDDING_SEND_DIM:
            params["dimensions"] = PROJECT_CONFIG.EMBEDDING_DIM

        try:
            response = await client.embeddings.create(**params)
        except Exception as exc:
            _reset_shared_client_on_connection_error(exc)
            raise
        # base64 分支显式小端 float32（OpenAI 兼容格式约定小端）:
        # np.float32 取本机字节序, 非小端平台会解析出错误数值
        return np.array(
            [
                np.array(dp.embedding, dtype=np.float32)
                if isinstance(dp.embedding, list)
                else np.frombuffer(
                    base64.b64decode(dp.embedding), dtype=np.dtype("<f4")
                )
                for dp in response.data
            ]
        )


@retry(
    stop=_EmbedStop(),
    wait=_EmbedWait(),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
async def _embed_batch(
        texts: List[str],
        semaphore: asyncio.Semaphore,
        trunc_counter: Optional[List[int]] = None,
) -> np.ndarray:
    """文档路径批次嵌入: 完整重试策略（限流 10 次尝试 + 20~60s 随机退避）。"""
    return await _embed_batch_call(texts, semaphore, trunc_counter)


@retry(
    stop=_EmbedStop(quick=True),
    wait=_EmbedWait(quick=True),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
async def _embed_batch_quick(
        texts: List[str],
        semaphore: asyncio.Semaphore,
        trunc_counter: Optional[List[int]] = None,
) -> np.ndarray:
    """查询路径批次嵌入: 快速失败（统一 3 次尝试、短等待）, 避免限流时挂死交互请求。"""
    return await _embed_batch_call(texts, semaphore, trunc_counter)


# ==================== 批量调度 ====================

async def embed_texts(texts: List[str], quick: bool = False) -> List[List[float]]:
    """批量获取文本向量, 空文本以零向量占位, 返回与输入等长的向量列表。

    :param quick: 查询场景快速失败模式（重试次数少、限流等待短）;
        文档嵌入走完整策略（限流时长退避多尝试, 宁可慢也要成）。
    """
    if not texts:
        return []
    # 维度前置校验（进程级一次）: 配置维度与实际模型不一致时秒级失败,
    # 而非等整条流水线跑完在向量库 upsert 时才炸
    await _verify_embedding_dim()

    clean = [(i, t) for i, t in enumerate(texts) if t and len(t.strip()) > 0]
    if not clean:
        return [[0.0] * PROJECT_CONFIG.EMBEDDING_DIM for _ in texts]

    # 限流: Windows 的 asyncio SelectorEventLoop 基于 select(), 有 512 个 socket
    # 的硬上限（FD_SETSIZE）; 大文档上千个批次同时发起会抛
    # "too many file descriptors in select()" 并直接打死 Worker 的事件循环线程
    semaphore = asyncio.Semaphore(PROJECT_CONFIG.EMBEDDING_MAX_CONCURRENT)
    batches: List[List[str]] = [
        [t for _, t in clean[start:start + PROJECT_CONFIG.EMBEDDING_BATCH_NUM]]
        for start in range(0, len(clean), PROJECT_CONFIG.EMBEDDING_BATCH_NUM)
    ]
    trunc_counter: List[int] = [0]  # 本次调用被截断的文本数（批次任务内累加）
    batch_fn = _embed_batch_quick if quick else _embed_batch
    # return_exceptions: 单个批次的瞬时失败不立即中止整个 gather, 改为收集失败批次统一补救
    results: List[Any] = list(
        await asyncio.gather(
            *(batch_fn(b, semaphore, trunc_counter) for b in batches),
            return_exceptions=True,
        )
    )

    # 任务取消 (Worker 关停等) 应立即传播, 不进入补救逻辑
    for r in results:
        if isinstance(r, asyncio.CancelledError):
            raise r

    failed_idx = [i for i, r in enumerate(results) if isinstance(r, BaseException)]
    if failed_idx:
        # 补救重试: 此时其余批次已完成、限流窗口通常已过, 给失败批次再一次机会
        # (每个批次自身仍带 tenacity 长退避重试)
        retried = await asyncio.gather(
            *(batch_fn(batches[i], semaphore, trunc_counter) for i in failed_idx),
            return_exceptions=True,
        )
        for i, r in zip(failed_idx, retried):
            results[i] = r
        still_failed = [i for i in failed_idx if isinstance(results[i], BaseException)]
        if still_failed:
            first = results[still_failed[0]]
            raise RuntimeError(
                f"向量嵌入失败: {len(still_failed)}/{len(batches)} 个批次重试后仍失败, "
                f"首个错误: {type(first).__name__}: {first}"
            ) from first

    # 严格校验每批返回数量: 下方映射按游标顺序回填, 若某批返回条数
    # 缺失, 向量会被错位绑定到错误文本——比直接失败更隐蔽, 故宁可失败
    for b, r in zip(batches, results):
        if len(r) != len(b):
            raise RuntimeError(
                f"向量嵌入批次返回数量不匹配: 请求 {len(b)} 条, 返回 {len(r)} 条"
            )

    out = [None] * len(texts)
    vi = 0
    for r in results:
        for vec in r:
            if vi < len(clean):
                out[clean[vi][0]] = vec.tolist()
                vi += 1
    dim = PROJECT_CONFIG.EMBEDDING_DIM
    for i in range(len(out)):
        if out[i] is None:
            out[i] = [0.0] * dim

    # 截断可观测: 截断会使分块尾部内容不参与向量化（尾部关键词检索
    # 命不中）, 不能再像旧实现一样完全静默。上限配置合理（覆盖最大
    # 分块长度）时正常不应出现截断, 出现即提示检查分块/上限口径
    if trunc_counter[0]:
        LOGGER.warning(
            f"向量嵌入: {trunc_counter[0]}/{len(clean)} 条文本超过 "
            f"{PROJECT_CONFIG.EMBEDDING_MAX_CHARS_PER_TEXT} 字符被截断, "
            f"超限内容不参与向量化（请核对分块大小配置或调高 EMBEDDING_MAX_CHARS_PER_TEXT）"
        )

    return out


# 进程级维度校验状态: 首次嵌入调用时探测一次, 通过则后续调用零开销
_dim_verified: bool = False


async def _verify_embedding_dim() -> None:
    """校验实际嵌入模型的向量维度与 ``EMBEDDING_DIM`` 配置一致（进程级一次）。

    向量库集合按配置维度建 schema, 维度不一致时所有 upsert 必然失败——
    与其让文档在流水线最后一步（解析/术语/嵌入的算力全部消耗完）才失败,
    不如在首次嵌入前用一条探针文本秒级发现。
    """
    global _dim_verified
    if _dim_verified:
        return
    client = _get_client()
    # 探针强制 float 编码: base64 字符串的 len() 不是维度
    response = await client.embeddings.create(
        model=PROJECT_CONFIG.EMBEDDING_MODEL,
        input=["dimension probe"],
        encoding_format="float",
    )
    actual = len(response.data[0].embedding)
    if actual != PROJECT_CONFIG.EMBEDDING_DIM:
        raise RuntimeError(
            f"嵌入模型维度不匹配: 配置 EMBEDDING_DIM={PROJECT_CONFIG.EMBEDDING_DIM}, "
            f"模型 {PROJECT_CONFIG.EMBEDDING_MODEL} 实际返回 {actual} 维。"
            f"向量库集合按配置维度创建, 请修正配置使其一致（换模型需同步重建向量集合）"
        )
    _dim_verified = True


async def embed_chunks(
        chunks: List[Dict[str, Any]],
        quick: bool = False,
) -> List[Dict[str, Any]]:
    """为分块列表就地补充 vector 字段。"""
    texts = [c.get("content", "") for c in chunks]
    vectors = await embed_texts(texts, quick=quick)
    for c, v in zip(chunks, vectors):
        c["vector"] = v
    return chunks


async def save_embeddings(chunks: List[Dict[str, Any]], output_path: str) -> str:
    """将分块向量持久化为 embeddings.json, 返回文件绝对路径。"""
    from applications.knowledge_base.rag.section_context import SECTION_METADATA_KEYS
    out = {
        f"chunk-{i:04d}": {
            "content": c.get("content", ""),
            "tokens": c.get("tokens", 0),
            "chunk_order_index": c.get("chunk_order_index", i),
            "modality": c.get("modality", "text"),
            "vector": c.get("vector", []),
            **{key: c[key] for key in SECTION_METADATA_KEYS if key in c},
        }
        for i, c in enumerate(chunks)
    }
    path = Path(output_path) / "embeddings.json"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return str(path.resolve())
