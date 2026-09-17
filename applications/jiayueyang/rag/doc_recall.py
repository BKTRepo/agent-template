# -*- coding: utf-8 -*-
"""文档级召回 — 文档摘要索引 + 定向注入（多文档联合检索的"保证"层）。

分块级 top-k 检索回答"哪些段落像问题", 文档级召回回答"哪些文档与问题
有关"。两者互补: 文档只有一小段相关时, 其分块相似度可能被大文档的海量
分块稀释、进不了候选池; 而摘要向量匹配的是"这份文档讲什么", 能把被稀释
的文档捞回来。

**双闸门设计（噪音安全）**: 摘要索引只负责把命中文档的分块送进重排
候选池, 进不进最终窗口仍只由 rerank 的 RERANK_MIN_SCORE 决定。摘要匹配
误报的文档, 其分块在重排拿不到阈值分自然出局——召回要宽、入口要严。

索引实现仿照 BM25 的指纹缓存模式: 文档表指纹（complete 文档的
job_id + updated_time）+ TTL 两级判据, 稳态查询不重复读盘; 文档就几十份,
命中判定为内存余弦, 微秒级。查询向量复用主查询嵌入, 不新增嵌入调用。
"""
import asyncio
import hashlib
import json
import math
import time as _time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from configure import LOGGER, PROJECT_CONFIG

from applications.jiayueyang.rag.milvus_store import query_chunks_by_doc

# ==================== 摘要索引缓存 ====================

_INDEX_CACHE: List[Dict[str, Any]] = []   # [{doc_id, file_path, summary, vector}]
_INDEX_FINGERPRINT: str = ""
_INDEX_EXPIRES_AT: float = 0.0


async def _load_summary_index() -> Tuple[str, List[Dict[str, Any]]]:
    """从文档表 + bundle 目录读取全部 complete 文档的摘要向量。

    :return: (文档表指纹, 索引条目列表); 指纹为 complete 文档
        job_id+updated_time 的有序哈希, 任一文档增删/重跑即变化。
    """
    # 延迟导入: 避免模块加载期引入 Tortoise/应用层依赖
    from applications.jiayueyang.services.rag_document_crud import RagDocumentCrud

    docs = await RagDocumentCrud().list_all()
    completed = [d for d in docs if d.status == "complete"]
    fingerprint = hashlib.md5(
        "|".join(sorted(f"{d.job_id}:{d.updated_time}" for d in completed)).encode()
    ).hexdigest()

    index: List[Dict[str, Any]] = []
    for d in completed:
        bundle_dir = d.output_path or ""
        if not bundle_dir:
            continue
        summary_file = Path(bundle_dir) / "summary.json"
        if not summary_file.is_file():
            continue  # 存量文档未生成摘要（回填脚本补齐后即纳入）
        try:
            data = json.loads(summary_file.read_text(encoding="utf-8"))
            vector = data.get("vector") or []
            summary = (data.get("summary") or "").strip()
            if not vector or not summary:
                continue
            index.append({
                "doc_id": d.job_id,
                "file_path": d.filename,  # 与向量库 file_path 同口径（引用分组键）
                "summary": summary,
                "vector": [float(x) for x in vector],
            })
        except Exception as e:
            LOGGER.warning(f"摘要索引跳过不可读产物: {summary_file}, {e}")
    return fingerprint, index


async def get_summary_index() -> List[Dict[str, Any]]:
    """获取文档摘要索引（TTL + 指纹两级缓存, 懒重建）。"""
    global _INDEX_CACHE, _INDEX_FINGERPRINT, _INDEX_EXPIRES_AT

    now = _time.time()
    if _INDEX_CACHE and now < _INDEX_EXPIRES_AT:
        return _INDEX_CACHE

    try:
        fingerprint, index = await _load_summary_index()
    except Exception:
        LOGGER.opt(exception=True).warning("文档摘要索引构建失败, 文档级召回本次跳过")
        # 有旧索引则继续用旧索引（优于空）, 冷启动则为空
        _INDEX_EXPIRES_AT = now + PROJECT_CONFIG.DOC_RECALL_INDEX_TTL
        return _INDEX_CACHE

    if fingerprint != _INDEX_FINGERPRINT:
        _INDEX_CACHE = index
        _INDEX_FINGERPRINT = fingerprint
        LOGGER.info(f"文档摘要索引已重建: {len(index)} 份文档")
    elif not _INDEX_CACHE:
        _INDEX_CACHE = index
    _INDEX_EXPIRES_AT = now + PROJECT_CONFIG.DOC_RECALL_INDEX_TTL
    return _INDEX_CACHE


# ==================== 摘要匹配 ====================

def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def match_documents(
        query_vector: List[float],
        index: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """查询向量 vs 文档摘要索引, 返回达标文档（相似度降序, 截断至上限）。

    :return: ``[{"doc_id", "file_path", "summary", "score"}, ...]``
    """
    if not query_vector or not index:
        return []
    scored: List[Dict[str, Any]] = []
    for entry in index:
        score = _cosine(query_vector, entry["vector"])
        if score >= PROJECT_CONFIG.DOC_RECALL_MIN_SCORE:
            scored.append({
                "doc_id": entry["doc_id"],
                "file_path": entry["file_path"],
                "summary": entry["summary"],
                "score": score,
            })
    scored.sort(key=lambda d: -d["score"])
    return scored[: PROJECT_CONFIG.DOC_RECALL_MAX_DOCS]


# ==================== 定向注入 ====================

async def recall_doc_chunks(
        query_vectors: List[List[float]],
) -> List[Dict[str, Any]]:
    """文档级召回全流程: 摘要索引匹配 → 命中文档定向取 top 分块。

    返回按文档相似度降序拼接的排名列表（直接作为一路进 RRF 融合）;
    任何环节失败均返回空列表——文档级召回是增强通道, 不得劣化主检索。
    """
    try:
        index = await get_summary_index()
        if not index:
            return []
        hits = match_documents(query_vectors[0], index)
        if not hits:
            return []

        LOGGER.info(
            "文档级召回命中: "
            + ", ".join(f"{h['file_path']}({h['score']:.3f})" for h in hits)
        )

        # 各命中文档的定向检索并行执行（RPC 阻塞调用移交线程池）
        per_doc = await asyncio.gather(
            *[
                asyncio.to_thread(
                    query_chunks_by_doc,
                    query_vectors,
                    h["doc_id"],
                    PROJECT_CONFIG.DOC_RECALL_CHUNKS_PER_DOC,
                )
                for h in hits
            ],
            return_exceptions=True,
        )

        ranked: List[Dict[str, Any]] = []
        seen: set = set()
        for chunks in per_doc:
            if isinstance(chunks, Exception) or not chunks:
                if isinstance(chunks, Exception):
                    LOGGER.warning(f"定向注入单文档失败（跳过该文档）: {chunks}")
                continue
            for c in chunks:
                cid = c.get("id")
                if cid and cid in seen:
                    continue
                if cid:
                    seen.add(cid)
                ranked.append(c)
        return ranked
    except Exception:
        LOGGER.opt(exception=True).warning("文档级召回失败, 本次跳过（不影响主检索）")
        return []
