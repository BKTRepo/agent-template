"""仅在用户有权且当前加载的知识库中检索 Milvus。"""

import asyncio
import json

from applications.knowledge_base.models.knowledge_base_model import Document, DocumentChunk
from applications.knowledge_base.services.platform_service import KnowledgeService
from applications.knowledge_base.rag.embedding import embed_texts
from applications.knowledge_base.rag.milvus_store import hybrid_query_chunks


async def allowed_jobs(user, knowledge_base_ids):
    ids = list(dict.fromkeys(knowledge_base_ids))
    for kb_id in ids:
        await KnowledgeService().require(kb_id, user)
    if not ids:
        return set()
    documents = await Document.filter(knowledge_base_id__in=ids, is_deleted=False, status="completed").values_list("id", flat=True)
    if not documents:
        return set()
    # DocumentChunk 只保存当前代次，避免召回替换文档后残留的旧向量。
    metadata = await DocumentChunk.filter(document_id__in=documents).values_list("source_metadata", flat=True)
    return {item["job_id"] for item in metadata if isinstance(item, dict) and item.get("job_id")}


async def retrieve(user, knowledge_base_ids, question, top_k=8):
    jobs = await allowed_jobs(user, knowledge_base_ids)
    if not jobs:
        return []
    vectors = await embed_texts([question])
    if not vectors:
        raise RuntimeError("知识库查询向量生成失败")
    expression = "doc_id in " + json.dumps(sorted(jobs), ensure_ascii=True)
    chunks = await asyncio.to_thread(hybrid_query_chunks, vectors, question, top_k=top_k, filter_expr=expression)
    current_jobs = await allowed_jobs(user, knowledge_base_ids)
    return [row for row in chunks if row.get("doc_id") in jobs and row.get("doc_id") in current_jobs]
