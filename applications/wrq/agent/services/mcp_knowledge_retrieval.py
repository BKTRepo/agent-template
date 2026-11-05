"""Agent MCP evidence retrieval, independent of the conversational query pipeline.

Only the unmodified agent query is embedded and sent to Dense + BM25/RRF,
then to the existing reranker. No rewriting, subqueries, translation, document
summary recall, conversation memory or answer generation runs in this path.
"""
import asyncio
import json

from configure import LOGGER
from applications.knowledge_base.rag.embedding import embed_texts
from applications.knowledge_base.rag.milvus_store import hybrid_query_chunks
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from applications.wrq.knowledge_base.config import PROJECT_CONFIG
from applications.wrq.knowledge_base.rag.rerank import rerank_chunks


async def retrieve_mcp_chunks(query, scope, top_k):
    metadata = dict(pipeline='mcp_hybrid_rerank', candidate_count=0, rerank='skipped')
    allowed = {job: set(doc['chunk_ids']) for doc in scope for job in doc['jobs']}
    if not allowed:
        return [], metadata

    vectors = await embed_texts([query])
    # Retrieve a candidate pool before reranking; top_k limits final evidence only.
    chunks = await asyncio.to_thread(
        hybrid_query_chunks, vectors, query,
        top_k=max(top_k, PROJECT_CONFIG.RRF_TOP_K),
        dense_top_k=PROJECT_CONFIG.HYBRID_DENSE_TOP_K,
        bm25_top_k=PROJECT_CONFIG.HYBRID_BM25_TOP_K,
        filter_expr='doc_id in ' + json.dumps(sorted(allowed)),
    )
    candidates, seen = [], set()
    for chunk in chunks:
        chunk_id = chunk['id']
        # Validate every candidate before any source text reaches the rerank API.
        if chunk_id not in allowed.get(chunk['doc_id'], set()):
            raise DeveloperError('检索结果不属于授权索引', 409)
        if chunk_id not in seen:
            candidates.append(chunk)
            seen.add(chunk_id)
    metadata['candidate_count'] = len(candidates)
    if not candidates:
        return [], metadata

    try:
        ranked = await asyncio.wait_for(
            rerank_chunks(query=query, chunks=candidates, top_n=top_k), timeout=20.0,
        )
        # The shared reranker returns original candidates on service failure.
        if ranked and all('rerank_score' in chunk for chunk in ranked):
            metadata['rerank'] = 'success'
        else:
            ranked = candidates
            metadata['rerank'] = 'fallback'
    except Exception as exc:
        LOGGER.warning('MCP知识库重排降级，保留RRF结果: {}', type(exc).__name__)
        ranked = candidates
        metadata['rerank'] = 'fallback'
    return ranked[:top_k], metadata
