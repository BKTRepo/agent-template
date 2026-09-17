# -*- coding: utf-8 -*-
"""查询逻辑 — naive RAG 检索与 bypass 直通模式, 实现移植自 LightRAG 的 naive_query()。

naive 模式流程:
    1. 查询向量化 → 检索向量库 → 取 top_k 个分块
    2. 计算动态 token 预算
    3. 由分块生成引用列表
    4. 按 token 预算截断分块
    5. 构建上下文字符串 (JSON 分块 + 引用列表)
    6. 构建系统提示词 (RAG_PROMPTS["naive_rag_response"])
    7. 调用 LLM → 返回响应 (流式或非流式)

bypass 模式完全跳过检索 — 直接与 LLM 对话。
"""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

from configure import LOGGER, PROJECT_CONFIG, RAG_PROMPTS

from applications.jiayueyang.rag.embedding import embed_texts
from applications.jiayueyang.rag.llm import chat_completion
from applications.jiayueyang.rag.rerank import rerank_chunks
from applications.jiayueyang.rag.doc_recall import recall_doc_chunks
from applications.jiayueyang.rag.memory import estimate_tokens, history_token_count
from applications.jiayueyang.rag.query_rewriter import (
    BilingualQuery,
    resolve_query_with_history,
    rewrite_query_bilingual,
)
from applications.jiayueyang.rag.subquery import decompose_query
from applications.jiayueyang.rag.milvus_store import (
    get_collection_stats,
    hybrid_query_chunks,
    query_chunks,
)

# ==================== 数据结构 ====================


@dataclass
class QueryParam:
    """查询参数, 与 LightRAG 的 QueryParam 保持兼容。"""

    mode: str = "naive"  # "naive" | "bypass"
    response_type: str = "Multiple Paragraphs"
    stream: bool = False
    chunk_top_k: Optional[int] = PROJECT_CONFIG.CHUNK_TOP_K  # naive 模式稠密检索条数
    rrf_top_k: Optional[int] = PROJECT_CONFIG.RRF_TOP_K  # hybrid 模式 RRF 融合保留条数（重排候选池）
    dense_top_k: Optional[int] = None  # 混合模式下单独的 dense top-k
    bm25_top_k: Optional[int] = None  # 混合模式下单独的 bm25 top-k
    max_total_tokens: int = PROJECT_CONFIG.MAX_TOTAL_TOKENS
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    # 滚动摘要（早期轮次压缩后的背景上下文）, 三模式统一注入 system 提示词
    conversation_summary: str = ""
    # L4 向量回忆: 按当前问题召回的本会话旧轮次（Q/A 文本）, 注入 system 提示词
    conversation_recall: str = ""
    user_prompt: Optional[str] = None
    enable_cot: bool = True  # 思维链推理 (简单事实类查询可置 False)
    enable_rerank: bool = True  # 默认开启重排: RRF 只融合排名不判相关性, 重排是精度闸门
    only_need_context: bool = False
    only_need_prompt: bool = False
    temperature: Optional[float] = None
    model: Optional[str] = None  # 指定生成模型（None 时用配置的 LLM_MODEL）


@dataclass
class QueryResult:
    """统一查询结果, 与 LightRAG 的 QueryResult 保持兼容。"""

    content: Optional[str] = None
    response_iterator: Optional[AsyncIterator[str]] = None
    raw_data: Optional[Dict[str, Any]] = None
    is_streaming: bool = False


# ==================== Token 预算 (基于字符数估算 — 不依赖真实分词器) ====================

_CHARS_PER_TOKEN = 1.8  # 中英文混合文本的保守估算 (每个 token 约 1.5-2.0 个汉字)


def _estimate_tokens(text: str) -> int:
    """粗略估算中英文混合文本的 token 数。"""
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def _compute_token_budget(
        sys_prompt_template: str,
        response_type: str,
        user_prompt: Optional[str],
        query: str,
        max_total_tokens: int,
        history_tokens: int = 0,
        summary_tokens: int = 0,
) -> int:
    """扣除固定开销后, 返回可供分块使用的 token 数。

    与 LightRAG 的做法一致:
    1. 用空内容占位符格式化系统提示词
    2. 从总预算中减去 系统提示词 + 查询 + 历史窗口 + 滚动摘要 + 200 token 缓冲

    历史窗口与滚动摘要都会注入 LLM、同样消耗上下文, 必须计入预算,
    否则长对话会让"系统提示 + 分块 + 摘要 + 历史 + 查询"总和超出上下文窗口。
    """
    user_prompt_str = f"\n\n{user_prompt}" if user_prompt else "n/a"
    pre_sys_prompt = sys_prompt_template.format(
        response_type=response_type,
        user_prompt=user_prompt_str,
        content_data="",  # 计算开销时置空
    )
    sys_prompt_tokens = _estimate_tokens(pre_sys_prompt)
    query_tokens = _estimate_tokens(query)
    buffer_tokens = 200
    available = max_total_tokens - (
        sys_prompt_tokens + query_tokens + history_tokens + summary_tokens + buffer_tokens
    )
    return max(available, 1200)  # 保底预算


# ==================== 向量上下文检索 ====================


async def _get_vector_context(
        query: str,
        top_k: int,
        query_vecs: Optional[List[List[float]]] = None,
) -> List[Dict[str, Any]]:
    """从向量库检索文本分块 (仅稠密向量)。

    :param query_vecs: 预计算的查询向量（多路召回共享主查询嵌入, 避免重复
        嵌入调用）; 缺省时当场嵌入。
    """
    if query_vecs is None:
        # quick 模式: 查询与文档嵌入共享同一 API Key, 大文档嵌入打满 TPM
        # 配额时查询嵌入会撞 429——快速失败（3 次短等待）而非挂死数分钟
        query_vecs = await embed_texts([query], quick=True)
    # 同步检索移交线程池（见后端导入处注释）
    return await asyncio.to_thread(query_chunks, query_vecs, top_k=top_k)


async def _warn_if_store_unreachable(context: str) -> None:
    """检索零命中但向量库非空 → 判定为存储层故障并告警。

    稠密检索对非空库必然返回 top_k 个最近邻（无相似度阈值过滤）,
    因此"库非空却零命中"只会发生在存储层异常（RPC 失败/超时被
    query_chunks 内部吞为空列表）时——与"查询确实不相关"区分开,
    避免检索静默退化为无上下文问答而无人察觉。
    """
    try:
        stats = await asyncio.to_thread(get_collection_stats)
        count = stats.get("chunk_count", 0)
        if count > 0:
            LOGGER.warning(
                f"{context}: 向量库存在 {count} 个分块但检索零命中, "
                f"疑似向量库访问故障（RPC 失败/超时）, 请检查 Worker 与 Milvus 状态"
            )
    except Exception:
        pass  # 诊断逻辑自身失败不得影响主流程


# ==================== 混合检索 (Milvus Dense + 内置 BM25 → RRF) ====================


def _rrf_merge(
        ranked_lists: List[List[Dict[str, Any]]],
        top_k: int,
        k: int = 60,
) -> List[Dict[str, Any]]:
    """倒数排名融合 (RRF) — 将任意数量的排名列表合并为一个。

    RRF score(d) = Σ 1/(k + rank_i(d))

    双通道召回下同一分块可能同时被 dense 与 BM25 命中,
    多列表命中时分数累加——双通道一致的块排名更高、更可信。
    """
    scores: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    for list_idx, ranked in enumerate(ranked_lists):
        for rank, c in enumerate(ranked):
            cid = c.get("id") or f"noid-{list_idx}-{rank}"
            rrf = 1.0 / (k + rank + 1)
            if cid in scores:
                old_rrf, old_c = scores[cid]
                old_c["_rrf_score"] = old_rrf + rrf
                scores[cid] = (old_rrf + rrf, old_c)
            else:
                c_copy = dict(c)
                c_copy["_rrf_score"] = rrf
                scores[cid] = (rrf, c_copy)

    merged = sorted(scores.values(), key=lambda x: -x[0])

    # 去重: 优先用 chunk ID（dense 与 BM25 来自同一向量库, ID 一致）,
    # ID 不可用时回退到内容前 200 字符哈希
    seen_ids: Set[str] = set()
    seen_hashes: Set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for item in merged[:top_k * 2]:  # 多取一些以补偿去重造成的缺口
        c = item[1]
        cid = c.get("id", "")
        if cid:
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            deduped.append(c)
        else:
            content_hash = hashlib.md5(
                c.get("content", "")[:200].encode()
            ).hexdigest()
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                deduped.append(c)
        if len(deduped) >= top_k:
            break

    return deduped


async def _retrieve_ranked_lists(
        queries: List[str],
        *,
        english_query: str = "",
        fusion_top_k: int,
        dense_top_k: int,
        bm25_top_k: int,
        enable_doc_recall: bool = False,
) -> List[List[Dict[str, Any]]]:
    """多查询并行调用 Milvus Dense + 双语 BM25 + RRF 混合检索。

    主查询同时走中文/英文 BM25，子查询走 Dense + 自身词项 BM25；文档级
    召回仍用主查询向量匹配摘要，并作为独立候选列表参与外层 RRF。

    :param queries: 检索查询集合, ``queries[0]`` 为主查询（改写后原句）,
        其余为子查询分解产物。
    """
    ranked_lists: List[List[Dict[str, Any]]] = []

    # 主查询嵌入只算一次: Dense 召回与文档级召回（摘要余弦）共享
    main_vecs = await embed_texts([queries[0]], quick=True)

    async def _hybrid_and_collect(
            q: str,
            vecs: List[List[float]],
            english: str = "",
    ) -> None:
        chunks = await asyncio.to_thread(
            hybrid_query_chunks,
            vecs,
            q,
            english,
            top_k=fusion_top_k,
            dense_top_k=dense_top_k,
            bm25_top_k=bm25_top_k,
        )
        if chunks:
            ranked_lists.append(chunks)

    async def _embed_and_hybrid(q: str) -> None:
        vecs = await embed_texts([q], quick=True)
        await _hybrid_and_collect(q, vecs)

    async def _doc_recall_and_collect() -> None:
        chunks = await recall_doc_chunks(main_vecs)
        if chunks:
            ranked_lists.append(chunks)

    tasks: List[asyncio.Task[None]] = [
        asyncio.create_task(_hybrid_and_collect(queries[0], main_vecs, english_query)),
    ]
    for q in queries[1:]:
        tasks.append(asyncio.create_task(_embed_and_hybrid(q)))
    if enable_doc_recall:
        tasks.append(asyncio.create_task(_doc_recall_and_collect()))
    await asyncio.gather(*tasks)

    return ranked_lists


def _merge_retrieval_queries(main_query: str, sub_queries: List[str]) -> List[str]:
    """检索查询集合 = 主查询 + 子查询（去重、去空）。

    保留主查询是对分解质量的兜底: 分解不当也不会丢失原始召回面。
    """
    queries = [main_query]
    for s in sub_queries or []:
        s = (s or "").strip()
        if s and s not in queries:
            queries.append(s)
    return queries


async def _get_hybrid_context(
        query: BilingualQuery,
        merge_top_k: int,
        *,
        dense_top_k: Optional[int] = None,
        bm25_top_k: Optional[int] = None,
        sub_queries: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """混合检索: 多查询 × 双通道（Dense + BM25）+ 文档级召回 → RRF 融合。

    只用改写后的查询检索（口语原文与文档词汇脱节, 召回会引入噪声）;
    Dense 擅长语义泛化, BM25 擅长精确关键词, 文档级召回补位被 top-k
    稀释掉的涉及文档, 全部候选经 RRF 融合为统一候选池。

    :param query: 主查询（含中文/英文分路检索词）。
    :param merge_top_k: RRF 融合后返回的分块数。
    :param dense_top_k: 每路稠密检索取多少分块。
    :param bm25_top_k: 每路 BM25 检索取多少分块。
    :param sub_queries: 子查询分解产物; 每面独立走双通道召回。
    """
    dk = dense_top_k or PROJECT_CONFIG.HYBRID_DENSE_TOP_K
    bk = bm25_top_k or PROJECT_CONFIG.HYBRID_BM25_TOP_K

    queries = _merge_retrieval_queries(query.primary_query, sub_queries or [])
    ranked_lists = await _retrieve_ranked_lists(
        queries,
        english_query=query.english_query,
        fusion_top_k=merge_top_k,
        dense_top_k=dk,
        bm25_top_k=bk,
        enable_doc_recall=PROJECT_CONFIG.DOC_RECALL_ENABLED,
    )

    # 至少有一路命中
    if not ranked_lists:
        return []

    # RRF 融合全部候选列表（dense/bm25/定向注入一视同仁）
    return _rrf_merge(ranked_lists, merge_top_k)


# ==================== 分块截断 ====================


def _truncate_chunks_by_tokens(
        chunks: List[Dict[str, Any]],
        max_tokens: int,
        doc_max_share: float = 1.0,
) -> List[Dict[str, Any]]:
    """按 token 预算保留分块, 累计超出 max_tokens 时停止。

    每个分块按 JSON 序列化后估算, 与 LLM 上下文字符串中的实际格式一致。

    单文档预算封顶（多文档联合检索保障）: 单个文档占用不得超过
    ``max_tokens × doc_max_share``, 超限分块进入延迟队列, 待其余文档分块
    按序消耗后以剩余预算按原序回填——
    - 单文档查询: 无其他文档竞争, 回填后结果与无封顶的顺序截断完全一致;
    - 多文档查询: 主导文档不再霸占窗口, 问题涉及的其他文档分块得以进入
      上下文。被延迟的分块均已通过重排相关性闸门, 回填不引入新噪声,
      只在已验证的证据之间重新分配预算。
    doc_max_share ≥ 1.0 时关闭封顶, 退化为纯顺序截断（旧行为）。
    """
    doc_budget: Optional[int] = (
        None if doc_max_share >= 1.0 else max(int(max_tokens * doc_max_share), 0)
    )

    def _chunk_tokens(c: Dict[str, Any]) -> int:
        serialized = json.dumps(
            {"reference_id": c.get("reference_id", ""), "content": c["content"]},
            ensure_ascii=False,
        )
        return _estimate_tokens(serialized)

    kept: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    doc_spent: Dict[str, int] = {}
    total = 0
    for c in chunks:
        chunk_tokens = _chunk_tokens(c)
        if total + chunk_tokens > max_tokens:
            break
        fp = _chunk_doc_key(c)
        if (
            doc_budget is not None
            and fp
            and doc_spent.get(fp, 0) + chunk_tokens > doc_budget
        ):
            deferred.append(c)  # 超出本文档预算上限, 待剩余预算回填
            continue
        kept.append(c)
        total += chunk_tokens
        if fp:
            doc_spent[fp] = doc_spent.get(fp, 0) + chunk_tokens

    # 回填: 被封顶延迟的分块按原相关性序消耗剩余预算
    for c in deferred:
        chunk_tokens = _chunk_tokens(c)
        if total + chunk_tokens > max_tokens:
            break
        kept.append(c)
        total += chunk_tokens

    return kept


# ==================== 文档级相关性聚合（动态加权的基础） ====================

# 相关性档位阈值（doc_score → 提示词级权重提示, 仅达标档位注入引用列表）
_DOC_TIER_HIGH = 0.8
_DOC_TIER_MID = 0.6


def _chunk_doc_key(chunk: Dict[str, Any]) -> str:
    """分块的文档身份键（引用分组 / 预算封顶核算 / 上下文排序共用）。"""
    fp = chunk.get("file_path", "") or chunk.get("file_name", "")
    return "" if fp == "unknown_source" else fp


def _aggregate_doc_scores(chunks: List[Dict[str, Any]]) -> Dict[str, float]:
    """将分块级 rerank 分数聚合为文档级相关性（查询条件下的动态权重）。

    doc_score = 0.7 × 该文档最高分块 + 0.3 × top-3 均值: 最高分捕捉"强命中",
    top-3 均值奖励"证据一致"（单块擦边与多块相关应当区分开）。仅统计带
    rerank_score 的分块——重排关闭/失败回退时全部无分, 引用排序退化为
    传统频次排序（行为与旧版一致）。
    """
    per_doc: Dict[str, List[float]] = {}
    for c in chunks:
        s = c.get("rerank_score")
        if s is None:
            continue
        fp = _chunk_doc_key(c)
        if fp:
            per_doc.setdefault(fp, []).append(float(s))

    scores: Dict[str, float] = {}
    for fp, ss in per_doc.items():
        ss.sort(reverse=True)
        top3 = ss[:3]
        scores[fp] = 0.7 * ss[0] + 0.3 * (sum(top3) / len(top3))
    return scores


def _relevance_tier(score: Optional[float]) -> Optional[str]:
    """doc_score → 相关性档位标签（未达标返回 None, 不标注）。"""
    if score is None:
        return None
    if score >= _DOC_TIER_HIGH:
        return "高度相关"
    if score >= _DOC_TIER_MID:
        return "相关"
    return None


# ==================== 引用列表生成 ====================


def _generate_reference_list(
        chunks: List[Dict[str, Any]],
        doc_scores: Optional[Dict[str, float]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """由分块生成引用列表（按文档相关性降序）, 并为分块标注 reference_id。

    排序依据: 有 doc_score 的文档按分数降序（动态权重决定来源展示与上下文
    排位）, 无分数的（重排关闭/失败回退）退回频次降序且整体排在有分数文档
    之后; 稳定排序保证同档内保持首次出现顺序。

    注意: 此处刻意不做"低占比文档剔除"——能走到这里的分块均已通过重排
    相关性闸门（RERANK_MIN_SCORE）与 token 预算截断, 噪声在检索侧重排环节
    控制, 引用层不再二次过滤。多文档联合检索场景下问题涉及的每份文档占比
    天然偏低（3 份文档各约 33%, 4 份各约 25%）, 占比阈值会把它们整体抹掉,
    导致文档明明被检索到、用户却看不到来源。

    :return: (reference_list, chunks_with_ref_ids)
        - reference_list: ``[{"reference_id", "file_path", "file_name",
          "relevance", "doc_score"}, ...]``（relevance/doc_score 供前端展示
          相关度, 旧前端忽略多余字段不受影响）
        - chunks_with_ref_ids: 附加了 ``reference_id`` 字段的分块
    """
    if not chunks:
        return [], []
    doc_scores = doc_scores or {}

    # 统计各 file_path 的出现次数
    file_path_counts: Dict[str, int] = {}
    for c in chunks:
        fp = _chunk_doc_key(c)
        if fp:
            file_path_counts[fp] = file_path_counts.get(fp, 0) + 1

    # 构建去重且保持出现顺序的文件路径列表
    seen: Set[str] = set()
    unique_paths: List[str] = []
    for c in chunks:
        fp = _chunk_doc_key(c)
        if fp and fp not in seen:
            unique_paths.append(fp)
            seen.add(fp)

    def _doc_sort_key(fp: str) -> Tuple[int, float, int]:
        s = doc_scores.get(fp)
        if s is not None:
            return (0, -s, -file_path_counts.get(fp, 0))
        return (1, 0.0, -file_path_counts.get(fp, 0))

    unique_paths.sort(key=_doc_sort_key)

    # 分配引用 ID: 排序后的 file_path 依次编号 1..N
    fp_to_ref_id: Dict[str, str] = {
        fp: str(i + 1) for i, fp in enumerate(unique_paths)
    }

    # 为分块标注 reference_id
    updated_chunks: List[Dict[str, Any]] = []
    for c in chunks:
        cc = dict(c)
        fp = _chunk_doc_key(cc)
        cc["reference_id"] = fp_to_ref_id.get(fp, "") if fp else ""
        updated_chunks.append(cc)

    reference_list: List[Dict[str, Any]] = []
    for i, fp in enumerate(unique_paths):
        s = doc_scores.get(fp)
        reference_list.append({
            "reference_id": str(i + 1),
            "file_path": fp,
            "file_name": Path(fp).name or fp,
            "relevance": _relevance_tier(s),
            "doc_score": round(s, 3) if s is not None else None,
        })
    return reference_list, updated_chunks


# ==================== LLM 上下文构建 ====================


def _build_llm_context(
        chunks: List[Dict[str, Any]],
        reference_list: List[Dict[str, Any]],
) -> str:
    """由分块与引用列表构建 LLM 提示词上下文字符串。

    保留上游重排的相关性顺序。旧实现会按“文档 + 原文顺序”重新排序，
    导致精确命中的高分块被同文档中较早但无关的分块挤到上下文后部。
    原文位置仍通过 chunk_order 提供，引用列表单独按文档相关性展示。
    """
    chunks_context: List[Dict[str, str]] = []
    for c in chunks:
        entry: Dict[str, str] = {
            "reference_id": c.get("reference_id", ""),
            "content": c["content"],
            "chunk_order": str(c.get("order", "")),
        }
        chunks_context.append(entry)

    text_units_str = "\n".join(
        json.dumps(tu, ensure_ascii=False) for tu in chunks_context
    )

    def _ref_line(r: Dict[str, Any]) -> str:
        line = f"[{r['reference_id']}] {r.get('file_name', r['file_path'])}"
        if r.get("relevance"):
            line += f"（{r['relevance']}）"
        return line

    reference_list_str = "\n".join(
        _ref_line(r) for r in reference_list if r["reference_id"]
    )

    return RAG_PROMPTS["naive_query_context"].format(
        text_chunks_str=text_units_str,
        reference_list_str=reference_list_str,
    )


# ==================== 检索为空兜底 ====================


async def _no_context_fallback(
        query: str,
        query_param: QueryParam,
        query_mode: str,
) -> QueryResult:
    """未检索到相关分块时的兜底通用对话（替代生硬拒绝）。

    打招呼 / 闲聊等场景下, 直接回"未找到相关文档分块"并不自然, 故改用
    兜底提示词调用 LLM: 闲聊自然回应; 询问知识库内容则温和提示暂无相关
    文档。对话历史经 history_messages 注入。
    """
    response = await chat_completion(
        messages=query,
        system_prompt=RAG_PROMPTS["no_context_fallback"],
        history_messages=query_param.conversation_history,
        conversation_summary=query_param.conversation_summary,
        conversation_recall=query_param.conversation_recall,
        stream=query_param.stream,
        temperature=query_param.temperature,
        model=query_param.model,
    )
    raw_data: Dict[str, Any] = {
        "data": {"entities": [], "relationships": [], "chunks": [], "references": []},
        "metadata": {
            "query_mode": query_mode,
            "total_chunks_found": 0,
            "final_chunks_count": 0,
        },
    }
    if isinstance(response, str):
        return QueryResult(content=response, raw_data=raw_data)
    return QueryResult(response_iterator=response, raw_data=raw_data, is_streaming=True)


# ==================== 主查询函数 ====================


async def naive_query(
        query: str,
        query_param: QueryParam,
) -> Optional[QueryResult]:
    """执行 naive 纯向量查询 (含术语改写)。

    完整流程:
        0. 基于术语索引改写查询 (指代消解 + 术语展开)
        1. 子查询分解（复合问题）+ 多路召回（每查询 Dense + 文档级召回,
           多路命中经 RRF 融合）→ 分块
        2. token 预算 → available_chunk_tokens
        3. 引用列表 → 为分块分配 reference_id
        4. token 截断 → 分块控制在预算内
        5. 构建上下文 → JSON 分块 + 引用列表字符串
        6. 构建系统提示词 → RAG_PROMPTS["naive_rag_response"]
        7. 调用 LLM → 流式或非流式

    未检索到分块时返回 None (由调用方展示 "无上下文" 提示)。
    """
    if not query:
        return QueryResult(content=RAG_PROMPTS["fail_response"])

    # 阶段 0a: 历史感知改写（指代消解）——多轮时用最近历史把当前问题消解为
    # 自包含查询, 仅用于检索（生成回答仍用原始问题 + 完整历史）
    resolved_query = await resolve_query_with_history(query, query_param.conversation_history)
    # 阶段 0b: 术语改写 + 英文检索词扩展（无术语索引时也生成英文查询）
    bilingual_query = await rewrite_query_bilingual(resolved_query)
    query_for_search = bilingual_query.primary_query

    search_top_k = query_param.chunk_top_k or PROJECT_CONFIG.CHUNK_TOP_K

    # 阶段 1: 子查询分解——复合问题拆为单面查询, 每面独立召回;
    # 原查询保留在检索集合中作为兜底（分解不当不丢原始召回面）
    sub_queries = await decompose_query(query_for_search)
    queries = _merge_retrieval_queries(query_for_search, sub_queries)

    # 阶段 2: 多路召回（每查询一路 Dense + 文档级召回）; 单查询单路命中
    # 时结果与旧版 top-k 语义一致, 多路命中经 RRF 融合为候选池
    ranked_lists = await _retrieve_ranked_lists(
        queries,
        english_query=bilingual_query.english_query,
        fusion_top_k=search_top_k,
        dense_top_k=search_top_k,
        bm25_top_k=PROJECT_CONFIG.HYBRID_BM25_TOP_K,
        enable_doc_recall=PROJECT_CONFIG.DOC_RECALL_ENABLED,
    )

    if not ranked_lists:
        await _warn_if_store_unreachable("naive 检索")
        return await _no_context_fallback(query, query_param, "naive")

    chunks = (
        ranked_lists[0]
        if len(ranked_lists) == 1
        else _rrf_merge(ranked_lists, search_top_k)
    )

    # 重排: 按改写后查询的相关性对分块重新打分（从候选池精选出最终检索窗口）
    if query_param.enable_rerank:
        try:
            reranked = await asyncio.wait_for(
                rerank_chunks(query=bilingual_query.rerank_query, chunks=chunks, top_n=PROJECT_CONFIG.RERANK_TOP_K),
                timeout=20.0,
            )
            if reranked:
                chunks = reranked
        except asyncio.TimeoutError:
            LOGGER.warning("重排超时 (20 秒), 使用原始分块")
        except Exception:
            LOGGER.opt(exception=True).warning("重排失败, 使用原始分块")

    total_chunks_found = len(chunks)
    chunks = chunks[:PROJECT_CONFIG.RAG_CONTEXT_TOP_K]

    # 计算动态 token 预算（历史窗口 + 滚动摘要计入预算）
    available_tokens = _compute_token_budget(
        RAG_PROMPTS["naive_rag_response"],
        query_param.response_type,
        query_param.user_prompt,
        query,
        query_param.max_total_tokens,
        history_tokens=history_token_count(query_param.conversation_history),
        summary_tokens=estimate_tokens(query_param.conversation_summary or ""),
    )

    # 聚合文档级相关性（查询条件下的动态权重）→ 引用列表按相关度降序
    doc_scores = _aggregate_doc_scores(chunks)

    # 生成引用列表并为分块标注
    reference_list, chunks_with_refs = _generate_reference_list(chunks, doc_scores)

    # 按 token 预算截断分块（单文档占比封顶, 防止主导文档独占检索窗口）
    processed_chunks = _truncate_chunks_by_tokens(
        chunks_with_refs, available_tokens, PROJECT_CONFIG.DOC_BUDGET_MAX_SHARE
    )

    if not processed_chunks:
        return await _no_context_fallback(query, query_param, "naive")

    # 构建响应的 raw_data
    raw_data: Dict[str, Any] = {
        "data": {
            "entities": [],
            "relationships": [],
            "chunks": processed_chunks,
            "references": reference_list,
        },
        "metadata": {
            "query_mode": "naive",
            "total_chunks_found": total_chunks_found,
            "context_candidate_count": len(chunks),
            "final_chunks_count": len(processed_chunks),
            "rewritten_query": (
                bilingual_query.primary_query
                if bilingual_query.primary_query != query
                else None
            ),
            "sub_queries": sub_queries or None,
        },
    }

    # 构建上下文字符串 (JSON 分块 + 引用列表)
    context_content = _build_llm_context(processed_chunks, reference_list)

    # 仅需上下文 / 仅需提示词模式下提前返回
    if query_param.only_need_context:
        return QueryResult(content=context_content, raw_data=raw_data)

    user_prompt_str = (
        f"\n\n{query_param.user_prompt}" if query_param.user_prompt else "n/a"
    )
    sys_prompt = RAG_PROMPTS["naive_rag_response"].format(
        response_type=query_param.response_type,
        user_prompt=user_prompt_str,
        content_data=context_content,
    )

    if query_param.only_need_prompt:
        prompt_content = f"{sys_prompt}\n\n---User Query---\n{query}"
        return QueryResult(content=prompt_content, raw_data=raw_data)

    # 调用 LLM
    response = await chat_completion(
        messages=query,
        system_prompt=sys_prompt,
        history_messages=query_param.conversation_history,
        conversation_summary=query_param.conversation_summary,
        conversation_recall=query_param.conversation_recall,
        stream=query_param.stream,
        enable_cot=query_param.enable_cot,
        temperature=query_param.temperature,
        model=query_param.model,
    )

    if isinstance(response, str):
        return QueryResult(content=response, raw_data=raw_data)
    else:
        return QueryResult(
            response_iterator=response, raw_data=raw_data, is_streaming=True
        )


async def hybrid_query(
        query: str,
        query_param: QueryParam,
) -> Optional[QueryResult]:
    """执行混合查询 — 术语改写 → Dense + BM25 → RRF 融合 → LLM。

    完整流程:
        0. 基于术语索引改写查询 (LLM + 缓存 + 规则兜底)
        1. 混合检索 (子查询分解 → 多查询 × Dense + BM25 + 文档级召回
           → RRF 融合) → 分块
        2. token 预算 → available_chunk_tokens
        3. 引用列表 → 为分块分配 reference_id
        4. token 截断 → 分块控制在预算内
        5. 构建上下文 → JSON 分块 + 引用列表字符串
        6. 构建系统提示词 → RAG_PROMPTS["naive_rag_response"]
        7. 调用 LLM → 流式或非流式

    未检索到分块时返回 None。
    """
    if not query:
        return QueryResult(content=RAG_PROMPTS["fail_response"])

    # 阶段 0a: 历史感知改写（指代消解）——多轮时用最近历史把当前问题消解为
    # 自包含查询, 仅用于检索（生成回答仍用原始问题 + 完整历史）
    resolved_query = await resolve_query_with_history(query, query_param.conversation_history)
    # 阶段 0b: 术语改写 + 英文检索词扩展
    bilingual_query = await rewrite_query_bilingual(resolved_query)

    # 阶段 1: 混合检索（仅改写查询 → Dense + BM25 → RRF 融合）。
    # 刻意不用原文查询召回: 口语原文（如 "3域"）词项与文档词汇脱节,
    # 并行召回会把无关块灌进候选池、稀释 RRF 排名; 改写查询已承载
    # 术语桥接, 原文意图仍用于最终 LLM 作答（见阶段 6 的 query 传参）
    merge_top_k = query_param.rrf_top_k or PROJECT_CONFIG.RRF_TOP_K
    query_for_search = bilingual_query.primary_query

    # 阶段 0c: 子查询分解——复合问题拆为单面查询, 每面独立走双通道召回;
    # 原查询保留在检索集合中作为兜底（分解不当不丢原始召回面）
    sub_queries = await decompose_query(query_for_search)

    chunks = await _get_hybrid_context(
        bilingual_query,
        merge_top_k=merge_top_k,
        dense_top_k=query_param.dense_top_k,
        bm25_top_k=query_param.bm25_top_k,
        sub_queries=sub_queries,
    )

    if not chunks:
        await _warn_if_store_unreachable("hybrid 检索")
        return await _no_context_fallback(query, query_param, "hybrid")

    # 重排: 按改写后查询的相关性对分块重新打分（从候选池精选出最终检索窗口）
    if query_param.enable_rerank:
        try:
            reranked = await asyncio.wait_for(
                rerank_chunks(query=bilingual_query.rerank_query, chunks=chunks, top_n=PROJECT_CONFIG.RERANK_TOP_K),
                timeout=20.0,
            )
            if reranked:
                chunks = reranked
        except asyncio.TimeoutError:
            LOGGER.warning("重排超时 (20 秒), 使用原始分块")
        except Exception:
            LOGGER.opt(exception=True).warning("重排失败, 使用原始分块")

    total_chunks_found = len(chunks)
    chunks = chunks[:PROJECT_CONFIG.RAG_CONTEXT_TOP_K]

    # 计算动态 token 预算 (用户可见的提示词使用原始查询; 历史窗口 + 滚动摘要计入预算)
    available_tokens = _compute_token_budget(
        RAG_PROMPTS["naive_rag_response"],
        query_param.response_type,
        query_param.user_prompt,
        query,  # LLM 提示词中使用原始查询
        query_param.max_total_tokens,
        history_tokens=history_token_count(query_param.conversation_history),
        summary_tokens=estimate_tokens(query_param.conversation_summary or ""),
    )

    # 聚合文档级相关性（查询条件下的动态权重）→ 引用列表按相关度降序
    doc_scores = _aggregate_doc_scores(chunks)

    # 生成引用列表并为分块标注
    reference_list, chunks_with_refs = _generate_reference_list(chunks, doc_scores)

    # 按 token 预算截断分块（单文档占比封顶, 防止主导文档独占检索窗口）
    processed_chunks = _truncate_chunks_by_tokens(
        chunks_with_refs, available_tokens, PROJECT_CONFIG.DOC_BUDGET_MAX_SHARE
    )

    if not processed_chunks:
        return await _no_context_fallback(query, query_param, "hybrid")

    # 构建响应的 raw_data
    raw_data: Dict[str, Any] = {
        "data": {
            "entities": [],
            "relationships": [],
            "chunks": processed_chunks,
            "references": reference_list,
        },
        "metadata": {
            "query_mode": "hybrid",
            "total_chunks_found": total_chunks_found,
            "context_candidate_count": len(chunks),
            "final_chunks_count": len(processed_chunks),
            "rewritten_query": (
                bilingual_query.primary_query
                if bilingual_query.primary_query != query
                else None
            ),
            "sub_queries": sub_queries or None,
        },
    }

    # 构建上下文字符串 (JSON 分块 + 引用列表)
    context_content = _build_llm_context(processed_chunks, reference_list)

    # 仅需上下文 / 仅需提示词模式下提前返回
    if query_param.only_need_context:
        return QueryResult(content=context_content, raw_data=raw_data)

    user_prompt_str = (
        f"\n\n{query_param.user_prompt}" if query_param.user_prompt else "n/a"
    )
    sys_prompt = RAG_PROMPTS["naive_rag_response"].format(
        response_type=query_param.response_type,
        user_prompt=user_prompt_str,
        content_data=context_content,
    )

    if query_param.only_need_prompt:
        prompt_content = f"{sys_prompt}\n\n---User Query---\n{query}"
        return QueryResult(content=prompt_content, raw_data=raw_data)

    # 调用 LLM
    response = await chat_completion(
        messages=query,
        system_prompt=sys_prompt,
        history_messages=query_param.conversation_history,
        conversation_summary=query_param.conversation_summary,
        conversation_recall=query_param.conversation_recall,
        stream=query_param.stream,
        enable_cot=query_param.enable_cot,
        temperature=query_param.temperature,
        model=query_param.model,
    )

    if isinstance(response, str):
        return QueryResult(content=response, raw_data=raw_data)
    else:
        return QueryResult(
            response_iterator=response, raw_data=raw_data, is_streaming=True
        )


async def bypass_query(
        query: str,
        query_param: QueryParam,
) -> QueryResult:
    """不经过知识检索, 直接调用 LLM 对话。

    历史对话经 history_messages 注入（与 naive/hybrid 统一, 无 {history} 占位符）。
    """
    if not query:
        return QueryResult(content=RAG_PROMPTS["fail_response"])

    sys_prompt = RAG_PROMPTS["bypass_system"]

    response = await chat_completion(
        messages=query,
        system_prompt=sys_prompt,
        history_messages=query_param.conversation_history,
        conversation_summary=query_param.conversation_summary,
        conversation_recall=query_param.conversation_recall,
        stream=query_param.stream,
        temperature=query_param.temperature,
        model=query_param.model,
    )

    if isinstance(response, str):
        return QueryResult(content=response)
    else:
        return QueryResult(response_iterator=response, is_streaming=True)


# ==================== 元问题路由（知识库目录类提问） ====================

# 元问题特征模式: 问的是"知识库里有什么文档", 而非任何文档的内容。
# 这类问题的答案分散在全库元数据中, 与任何具体分块都不强相关,
# 分块检索注定答不全（尤其文档体量悬殊时）, 应由文档表直接作答
_META_QUERY_PATTERNS = [
    re.compile(r"(知识库|资料库|文档库)[中里]?(?:都)?(有哪些|有什么|有些什么|都有什么|都有)"),
    re.compile(r"(有哪些|有几个|有几份|有多少|列出|列举|列一下).{0,6}(文档|文件|资料)"),
    re.compile(r"(文档|文件)(列表|清单)"),
    re.compile(r"上传了(什么|哪些|几[个份篇]|多少)"),
    re.compile(r"(有没有|有无|是否有).{0,16}(文档|文件|资料)"),
    re.compile(r"(一共|总共|目前|现在)?(?:有|上传了)?(几[个份篇]|多少)(?:个|份|篇)?(文档|文件|资料)"),
]

# 内容谓词: 出现即说明是在问文档内容（"有哪些文档提到了X"）, 不是元问题。
# 宁可漏路由（回退检索）, 不可误路由（拿目录答内容问题）
_META_CONTENT_PREDICATE = re.compile(
    r"提到|包含|涉及|关于|有关|描述|说明|介绍|规定|要求"
)

# 元问题长度上限: 目录类提问都是短句, 超长输入一律不路由
_META_QUERY_MAX_CHARS = 60


def _is_meta_query(query: str) -> bool:
    """判断是否为"知识库有哪些文档"类元问题（问目录本身, 不问文档内容）。

    带内容谓词的提问即便含"有哪些文档"字样也是在问内容, 不路由;
    规则不命中时回退正常检索流程, 行为不劣于路由前。
    """
    q = (query or "").strip()
    if not q or len(q) > _META_QUERY_MAX_CHARS:
        return False
    if _META_CONTENT_PREDICATE.search(q):
        return False
    return any(p.search(q) for p in _META_QUERY_PATTERNS)


async def _meta_catalog_response() -> Optional[QueryResult]:
    """由文档表直接生成知识库目录回答, 绕过向量检索。

    只列解析完成（status == complete）的文档; 数据库异常时返回 None,
    由调用方落回正常检索流程——路由失败不得劣于原行为。
    """
    try:
        from applications.jiayueyang.services.rag_document_crud import RagDocumentCrud

        docs = await RagDocumentCrud().list_all()
    except Exception:
        LOGGER.opt(exception=True).warning("元问题路由读取文档表失败, 回退正常检索")
        return None

    complete = [d for d in docs if d.status == "complete"]
    if complete:
        lines = ["当前知识库共有以下文档："]
        for i, d in enumerate(complete, 1):
            extras: List[str] = []
            if d.page_count:
                extras.append(f"{d.page_count} 页")
            if d.chunks_count:
                extras.append(f"{d.chunks_count} 个分块")
            suffix = f"（{'、'.join(extras)}）" if extras else ""
            lines.append(f"{i}. {d.filename}{suffix}")
        content = "\n".join(lines)
    else:
        content = "当前知识库中暂无已完成解析的文档，请先上传文档。"

    raw_data: Dict[str, Any] = {
        "data": {"entities": [], "relationships": [], "chunks": [], "references": []},
        "metadata": {
            "query_mode": "meta_catalog",
            "total_chunks_found": 0,
            "final_chunks_count": 0,
            "document_count": len(complete),
        },
    }
    return QueryResult(content=content, raw_data=raw_data)


async def run_query(
        query: str,
        query_param: QueryParam,
) -> QueryResult:
    """按查询模式分发到对应处理函数。"""
    # 元问题路由: "知识库有哪些文档"类提问直接由文档表作答, 不走检索。
    # bypass 模式本身就是纯对话, 不路由; 路由失败（返回 None）落回正常检索
    if query_param.mode != "bypass" and _is_meta_query(query):
        meta_result = await _meta_catalog_response()
        if meta_result is not None:
            return meta_result

    if query_param.mode == "bypass":
        return await bypass_query(query, query_param)
    elif query_param.mode == "hybrid":
        result = await hybrid_query(query, query_param)
        if result is None:
            return QueryResult(
                content="混合检索未找到相关的文档分块。请尝试更换提问方式，或先上传相关文档。",
                raw_data={
                    "data": {"entities": [], "relationships": [], "chunks": [], "references": []},
                    "metadata": {"query_mode": "hybrid"},
                },
            )
        return result
    elif query_param.mode in ("naive", "local", "global", "mix"):
        # 暂无知识图谱后端, 所有 KG 模式回退到 naive
        result = await naive_query(query, query_param)
        if result is None:
            return QueryResult(
                content="知识库中未找到相关的文档分块。请尝试更换提问方式，或先上传相关文档。",
                raw_data={
                    "data": {"entities": [], "relationships": [], "chunks": [], "references": []},
                    "metadata": {"query_mode": query_param.mode},
                },
            )
        return result
    else:
        raise ValueError(f"未知的查询模式: {query_param.mode}")
