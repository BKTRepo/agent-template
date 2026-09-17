# -*- coding: utf-8 -*-
"""旧知识库模块使用的 Milvus Server C/S 存储。"""

import json
import re
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List

from pymilvus import (
    AnnSearchRequest,
    CollectionSchema,
    DataType,
    FieldSchema,
    Function,
    FunctionType,
    MilvusClient,
    RRFRanker,
)

from configure import LOGGER, PROJECT_CONFIG
from common.milvus_pool import get_milvus_client_pool


_COLLECTION = "knowledge_base_chunks"
_ready = False
_ANALYZERS: Dict[str, Any] = {
    "analyzers": {
        "chinese": {"tokenizer": "jieba", "filter": ["cnalphanumonly", "lowercase"]},
        "english": {"type": "english"},
        "default": {"tokenizer": "jieba", "filter": ["cnalphanumonly", "lowercase"]},
    },
    "by_field": "language",
    "alias": {"cn": "chinese", "en": "english", "mixed": "default"},
}


@contextmanager
def _client() -> Iterator[MilvusClient]:
    uri = PROJECT_CONFIG.MILVUS_URI.strip()
    if not uri.lower().startswith(("http://", "https://")):
        raise ValueError("MILVUS_URI 必须指向独立 Milvus Server")
    pool = get_milvus_client_pool(
        uri=uri,
        user=PROJECT_CONFIG.MILVUS_USER or "",
        password=PROJECT_CONFIG.MILVUS_PASSWORD or "",
        token=PROJECT_CONFIG.MILVUS_TOKEN or "",
        max_size=PROJECT_CONFIG.MILVUS_POOL_SIZE,
        acquire_timeout=PROJECT_CONFIG.MILVUS_POOL_ACQUIRE_TIMEOUT,
        client_cls=MilvusClient,
    )
    with pool.connection() as value:
        yield value


def _ensure_collection(client: MilvusClient) -> None:
    global _ready
    if _ready:
        client.load_collection(_COLLECTION)
        return
    if client.has_collection(_COLLECTION):
        client.load_collection(_COLLECTION)
        _ready = True
        return

    schema = CollectionSchema(
        fields=[
            FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
            FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="filename", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="page_number", dtype=DataType.INT64),
            FieldSchema(name="embedding_model", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="language", dtype=DataType.VARCHAR, max_length=8),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(
                name="search_text",
                dtype=DataType.VARCHAR,
                max_length=65535,
                enable_analyzer=True,
                multi_analyzer_params=_ANALYZERS,
            ),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=PROJECT_CONFIG.EMBEDDING_DIM),
            FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="created_at", dtype=DataType.INT64),
        ],
        enable_dynamic_field=False,
    )
    schema.add_function(
        Function(
            name="search_text_bm25",
            function_type=FunctionType.BM25,
            input_field_names=["search_text"],
            output_field_names=["sparse_vector"],
        )
    )
    client.create_collection(_COLLECTION, schema=schema)
    indexes = MilvusClient.prepare_index_params()
    indexes.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    indexes.add_index(
        field_name="sparse_vector",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={"inverted_index_algo": "DAAT_MAXSCORE"},
    )
    indexes.add_index(field_name="kb_id", index_type="INVERTED")
    indexes.add_index(field_name="doc_id", index_type="INVERTED")
    client.create_index(_COLLECTION, indexes)
    client.load_collection(_COLLECTION)
    _ready = True


def _language(text: str) -> str:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if not cjk:
        return "en"
    if not latin:
        return "cn"
    ratio = cjk / (cjk + latin)
    return "mixed" if 0.15 <= ratio <= 0.85 else ("cn" if ratio > 0.5 else "en")


class MilvusStore:
    """知识库向量与 Milvus 内置 BM25 存储。"""

    def upsert_chunks(self, kb_id: str, chunks: List[dict]) -> List[str]:
        if not chunks:
            return []
        ids: List[str] = []
        rows: List[Dict[str, Any]] = []
        now = int(time.time())
        for chunk in chunks:
            vector_id = chunk.get("vector_id") or str(uuid.uuid4())
            content = str(chunk.get("content") or "")
            ids.append(vector_id)
            rows.append({
                "id": vector_id,
                "kb_id": str(kb_id),
                "doc_id": str(chunk.get("doc_id") or ""),
                "chunk_id": str(chunk.get("chunk_id") or ""),
                "filename": str(chunk.get("filename") or "")[:512],
                "page_number": int(chunk.get("page_number") or -1),
                "embedding_model": str(chunk.get("embedding_model") or "")[:256],
                "language": _language(content),
                "content": content,
                "search_text": content,
                "vector": chunk["embedding"],
                "created_at": now,
            })
        with _client() as client:
            _ensure_collection(client)
            for start in range(0, len(rows), max(1, PROJECT_CONFIG.VECTOR_UPSERT_BATCH_SIZE)):
                client.upsert(_COLLECTION, rows[start:start + PROJECT_CONFIG.VECTOR_UPSERT_BATCH_SIZE])
        return ids

    def search(
            self,
            knowledge_base_ids: List[str],
            query_embedding: List[float],
            query_text: str,
            top_k: int = None,
    ) -> List[dict]:
        if not knowledge_base_ids:
            return []
        top_k = top_k or PROJECT_CONFIG.RETRIEVAL_TOP_K
        expr = f"kb_id in {json.dumps([str(value) for value in knowledge_base_ids])}"
        analyzer = "cn" if re.search(r"[\u3400-\u9fff]", query_text) else "en"
        requests = [
            AnnSearchRequest(
                data=[query_embedding], anns_field="vector",
                param={"metric_type": "COSINE", "params": {}}, limit=max(top_k, 20), expr=expr,
            ),
            AnnSearchRequest(
                data=[query_text], anns_field="sparse_vector",
                param={"metric_type": "BM25", "params": {}, "analyzer_name": analyzer},
                limit=max(top_k, 20), expr=expr,
            ),
        ]
        with _client() as client:
            _ensure_collection(client)
            results = client.hybrid_search(
                _COLLECTION,
                reqs=requests,
                ranker=RRFRanker(60),
                limit=top_k,
                output_fields=[
                    "content", "kb_id", "doc_id", "chunk_id", "filename",
                    "page_number", "embedding_model",
                ],
            )
        hits: List[dict] = []
        for hit in results[0] if results else []:
            entity = hit.get("entity", {})
            page = int(entity.get("page_number", -1))
            hits.append({
                "id": hit["id"],
                "kb_id": entity.get("kb_id", ""),
                "doc_id": entity.get("doc_id", ""),
                "chunk_id": entity.get("chunk_id", ""),
                "filename": entity.get("filename", ""),
                "page_number": None if page < 0 else page,
                "embedding_model": entity.get("embedding_model", ""),
                "content": entity.get("content", ""),
                "score": hit.get("distance", 0.0),
            })
        return hits

    def _delete(self, field: str, value: str) -> None:
        try:
            with _client() as client:
                _ensure_collection(client)
                client.delete(_COLLECTION, filter=f"{field} == {json.dumps(str(value))}")
        except Exception as exc:
            LOGGER.error(f"[Milvus] 删除向量失败: field={field}, {exc}")

    def delete_by_kb(self, kb_id: str) -> None:
        self._delete("kb_id", kb_id)

    def delete_by_doc(self, doc_id: str) -> None:
        self._delete("doc_id", doc_id)

    def delete_by_chunk(self, chunk_id: str) -> None:
        self._delete("chunk_id", chunk_id)

    def delete_by_vector_id(self, vector_id: str) -> None:
        self._delete("id", vector_id)


milvus_store = MilvusStore()
