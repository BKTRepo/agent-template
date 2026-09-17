# -*- coding: utf-8 -*-
"""重排模块 — OpenAI 兼容重排 API 调用, 实现移植自 LightRAG 并简化为单一通用端点 (Jina/Cohere/OpenAI 兼容格式)。

接入 naive_query 流水线: 向量检索之后、token 截断之前, 由重排器对分块重新打分。
"""

import re
from typing import Any, Dict, List, Optional, Tuple

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from configure import LOGGER, PROJECT_CONFIG

# ==================== 重排用的文档切块 (长文档超出 token 上限时拆分) ====================

_CHARS_PER_TOKEN = 1.8  # 中英文混合文本的保守估算

# 表格解析器为可追溯性写入的“第 N 行/共 M 行”不是业务内容。若用户查询
# 本身包含代码值（例如 Visa DE39=11），这些序号会让重排模型把“第 11 行”
# 误判成精确命中。只在送给重排服务的副本中移除序号，引用原文保持不变。
_TABLE_ROW_ORDINAL_RE = re.compile(
    r"第\s*\d+\s*行(?:\s*/\s*共\s*\d+\s*行|中)?"
)


def _sanitize_for_rerank(text: str) -> str:
    """移除解析器生成、会污染数值相关性的表格行序号。"""
    return _TABLE_ROW_ORDINAL_RE.sub("表格行", text)


def _chunk_documents_for_rerank(
        documents: List[str],
        max_tokens: int = 480,
) -> Tuple[List[str], List[int]]:
    """将超长文档切分为符合 token 预算的子块。

    :return: (chunked_docs, original_indices) — 每个子块可映射回原始文档下标。
    """
    max_chars = int(max_tokens * _CHARS_PER_TOKEN)
    chunked: List[str] = []
    indices: List[int] = []

    for idx, doc in enumerate(documents):
        if len(doc) <= max_chars:
            chunked.append(doc)
            indices.append(idx)
        else:
            start = 0
            while start < len(doc):
                end = min(start + max_chars, len(doc))
                chunked.append(doc[start:end])
                indices.append(idx)
                if end >= len(doc):
                    break
                start = end  # 不做重叠 — 简单性取舍

    return chunked, indices


def _aggregate_chunk_scores(
        chunk_results: List[Dict[str, Any]],
        doc_indices: List[int],
        num_original_docs: int,
) -> List[Dict[str, Any]]:
    """将子块重排分数聚合回原始文档。

    采用 ``max`` 聚合 — 文档得分取其所有子块得分的最大值。
    """
    doc_scores: Dict[int, List[float]] = {i: [] for i in range(num_original_docs)}

    for result in chunk_results:
        chunk_idx = result["index"]
        score = result["relevance_score"]
        if 0 <= chunk_idx < len(doc_indices):
            original_idx = doc_indices[chunk_idx]
            doc_scores[original_idx].append(score)

    aggregated: List[Dict[str, Any]] = []
    for doc_idx, scores in doc_scores.items():
        if scores:
            aggregated.append(
                {"index": doc_idx, "relevance_score": max(scores)}
            )

    aggregated.sort(key=lambda x: x["relevance_score"], reverse=True)
    return aggregated


# ==================== 核心重排 API 调用 ====================


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def _rerank_api(
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """调用所配置的重排 API 端点。

    端点 ``RERANK_BINDING_HOST`` 需兼容 Jina/Cohere/OpenAI 格式。
    """
    if not PROJECT_CONFIG.RERANK_BINDING_HOST:
        raise ValueError("未配置 RERANK_BINDING_HOST")

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    api_key = PROJECT_CONFIG.RERANK_BINDING_API_KEY or "none"
    if api_key != "none":
        headers["Authorization"] = f"Bearer {api_key}"

    payload: Dict[str, Any] = {
        "model": PROJECT_CONFIG.RERANK_MODEL,
        "query": query,
        "documents": documents,
    }
    if top_n is not None:
        payload["top_n"] = top_n

    LOGGER.info(
        f"调用重排 API: 模型={PROJECT_CONFIG.RERANK_MODEL}, 查询长度={len(query)}, "
        f"文档数={len(documents)}, top_n={top_n}"
    )

    async with httpx.AsyncClient(
        trust_env=False,
        timeout=httpx.Timeout(15.0, connect=5.0),
    ) as client:
        response = await client.post(PROJECT_CONFIG.RERANK_BINDING_HOST, headers=headers, json=payload)
        if response.status_code != 200:
            raise httpx.HTTPStatusError(
                f"重排 API 调用失败, 状态码 {response.status_code}: {response.text[:500]}",
                request=response.request,
                response=response,
            )
        data = response.json()

    results = data.get("results", [])
    if not isinstance(results, list):
        LOGGER.warning(f"重排 API 返回了非预期的结果格式: {type(results)}")
        return []

    LOGGER.info(f"重排 API 返回 {len(results)} 条结果")
    return [
        {"index": r["index"], "relevance_score": r["relevance_score"]}
        for r in results
    ]


# ==================== 对外接口 ====================


async def rerank_chunks(
        query: str,
        chunks: List[Dict[str, Any]],
        top_n: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """按查询相关性对已检索分块重排。

    接入 naive_query 流水线, 位于向量检索与 token 截断之间。
    ``rerank_score < RERANK_MIN_SCORE`` 的分块会被丢弃。

    :param query: 用户查询字符串。
    :param chunks: 分块字典列表 (每个须含 ``content``)。
    :param top_n: 重排后最多返回的分块数。
    :return: 附带 ``rerank_score`` 字段、按相关性降序排列的分块; 失败时返回原始分块。
    """
    if not chunks:
        return []

    LOGGER.info(f"开始重排: 查询='{query[:80]}', 分块数={len(chunks)}")

    # 提取文档文本
    document_texts: List[str] = [
        _sanitize_for_rerank(c.get("content", "") or str(c)) for c in chunks
    ]

    # 可选: 长文档切块
    doc_indices: Optional[List[int]] = None
    documents_to_rank = document_texts
    original_top_n = top_n

    if PROJECT_CONFIG.RERANK_ENABLE_CHUNKING:
        documents_to_rank, doc_indices = _chunk_documents_for_rerank(
            document_texts, max_tokens=PROJECT_CONFIG.RERANK_MAX_TOKENS_PER_DOC
        )
        LOGGER.debug(f"已将 {len(document_texts)} 篇文档切分为 {len(documents_to_rank)} 个子文档用于重排")
        # 启用切块时, 先取全部子块分数, 再在文档级别聚合
        if top_n is not None:
            top_n = None  # 数量限制推迟到聚合之后

    try:
        results = await _rerank_api(query, documents_to_rank, top_n=top_n)
    except Exception as exc:
        LOGGER.warning(f"重排失败, 使用原始分块: {type(exc).__name__}: {exc}")
        return chunks

    if not results:
        LOGGER.info("重排未返回结果, 使用原始分块")
        return chunks

    # 启用切块时, 将结果聚合回原始文档
    if PROJECT_CONFIG.RERANK_ENABLE_CHUNKING and doc_indices:
        results = _aggregate_chunk_scores(
            results, doc_indices, len(document_texts)
        )
        if original_top_n is not None and len(results) > original_top_n:
            results = results[:original_top_n]

    # 构建附带分数的重排结果列表
    reranked: List[Dict[str, Any]] = []
    filtered_count = 0
    for r in results:
        idx = r["index"]
        score = r["relevance_score"]

        # 按最低分数阈值过滤
        if score < PROJECT_CONFIG.RERANK_MIN_SCORE:
            filtered_count += 1
            continue

        if 0 <= idx < len(chunks):
            chunk = dict(chunks[idx])
            chunk["rerank_score"] = score
            reranked.append(chunk)

    if filtered_count:
        LOGGER.info(
            f"重排过滤: {filtered_count}/{len(results)} 个分块低于最低分 "
            f"{PROJECT_CONFIG.RERANK_MIN_SCORE:.2f}"
        )

    LOGGER.info(f"重排完成: {len(reranked)} 个分块 (原 {len(chunks)} 个)")
    return reranked if reranked else chunks
