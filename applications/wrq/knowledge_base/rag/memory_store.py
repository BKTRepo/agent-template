import time
import json
from typing import Any, Dict, List, Optional
from pymilvus import MilvusClient, CollectionSchema, FieldSchema, DataType
from configure import LOGGER, PROJECT_CONFIG
from applications.knowledge_base.rag.milvus_store import _milvus_client, _truncate_bytes, _normalize_primary_key, _hit_value, _run_milvus_read_with_retry
_MEMORY_COLLECTION_NAME = "rag_chat_memory"

# VARCHAR 字节上限（Milvus 上限 65535, 预留余量）
_MEMORY_MAX_QUESTION_BYTES = 8192
_MEMORY_MAX_ANSWER_BYTES = 16384
_MEMORY_MAX_CONV_ID_BYTES = 64

_memory_collection_ready: bool = False


def _ensure_memory_collection(client: MilvusClient) -> None:  # type: ignore
    """对话记忆集合与索引不存在时创建, 随后加载。"""
    global _memory_collection_ready
    if _memory_collection_ready:
        try:
            client.load_collection(_MEMORY_COLLECTION_NAME)
        except Exception:
            pass
        return

    if client.has_collection(_MEMORY_COLLECTION_NAME):
        client.load_collection(_MEMORY_COLLECTION_NAME)
        _memory_collection_ready = True
        return

    schema = CollectionSchema(
        fields=[
            FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=256, is_primary=True),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=PROJECT_CONFIG.EMBEDDING_DIM),
            FieldSchema(name="conversation_id", dtype=DataType.VARCHAR, max_length=_MEMORY_MAX_CONV_ID_BYTES),
            FieldSchema(name="seq", dtype=DataType.INT64),
            FieldSchema(name="question", dtype=DataType.VARCHAR, max_length=_MEMORY_MAX_QUESTION_BYTES),
            FieldSchema(name="answer", dtype=DataType.VARCHAR, max_length=_MEMORY_MAX_ANSWER_BYTES),
            FieldSchema(name="created_at", dtype=DataType.INT64),
        ],
        enable_dynamic_field=True,
    )

    try:
        client.create_collection(collection_name=_MEMORY_COLLECTION_NAME, schema=schema)
    except Exception as create_err:
        # 并发竞争（另一进程刚建好）→ 直接加载; 其余情形上抛
        if client.has_collection(_MEMORY_COLLECTION_NAME):
            LOGGER.info(f"对话记忆集合已由其他进程创建, 直接加载: {create_err}")
            client.load_collection(_MEMORY_COLLECTION_NAME)
            _memory_collection_ready = True
            return
        raise

    from pymilvus.milvus_client.index import IndexParams

    _v_idx = IndexParams()
    _v_idx.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_index(collection_name=_MEMORY_COLLECTION_NAME, index_params=_v_idx)

    # conversation_id 标量索引: 加速按会话过滤召回与整会话删除
    try:
        _s_idx = IndexParams()
        _s_idx.add_index(field_name="conversation_id", index_type="INVERTED")
        client.create_index(collection_name=_MEMORY_COLLECTION_NAME, index_params=_s_idx)
    except Exception:
        pass  # 标量索引仅为性能优化

    client.load_collection(_MEMORY_COLLECTION_NAME)
    _memory_collection_ready = True


def upsert_chat_memory(records: List[Dict[str, Any]]) -> int:
    """写入/更新对话轮次记忆向量。

    :param records: 每条须含 id/vector/conversation_id/seq/question/answer。
    :return: 已写入条数。
    """
    if not records:
        return 0
    now = int(time.time())
    rows: List[Dict[str, Any]] = []
    for r in records:
        rows.append({
            "id": r["id"],
            "vector": r.get("vector", []),
            "conversation_id": _truncate_bytes(str(r.get("conversation_id", "")), _MEMORY_MAX_CONV_ID_BYTES),
            "seq": int(r.get("seq", 0)),
            "question": _truncate_bytes(r.get("question", ""), _MEMORY_MAX_QUESTION_BYTES),
            "answer": _truncate_bytes(r.get("answer", ""), _MEMORY_MAX_ANSWER_BYTES),
            "created_at": now,
        })
    with _milvus_client() as client:
        _ensure_memory_collection(client)
        client.upsert(collection_name=_MEMORY_COLLECTION_NAME, data=rows)
    return len(rows)


def search_chat_memory(
        query_vectors: List[List[float]],
        conversation_id: str,
        top_k: int = 3,
        max_seq: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """按向量相似度召回指定会话的旧轮次记忆。

    :param query_vectors: 查询向量列表。
    :param conversation_id: 仅召回该会话的记忆。
    :param top_k: 返回条数上限。
    :param max_seq: 仅召回 seq <= max_seq 的轮次（用于排除近期窗口内轮次）。
    :return: 轮次字典列表（question/answer/seq/distance）。
    """
    def _search_memory(client: Any) -> List[Dict[str, Any]]:
        _ensure_memory_collection(client)
        filter_expr = f'conversation_id == "{conversation_id}"'
        if max_seq is not None:
            filter_expr += f" and seq <= {int(max_seq)}"
        results = client.search(
            collection_name=_MEMORY_COLLECTION_NAME,
            data=query_vectors,
            limit=top_k,
            filter=filter_expr,
            output_fields=["question", "answer", "seq", "conversation_id"],
            search_params={"metric_type": "COSINE"},
        )
        if not results:
            return []
        hits = results[0]
        turns: List[Dict[str, Any]] = []
        for hit in hits:
            entity = hit.get("entity", {})
            turns.append({
                "question": entity.get("question", ""),
                "answer": entity.get("answer", ""),
                "seq": entity.get("seq", 0),
                "distance": hit.get("distance", None),
            })
        return turns

    try:
        return _run_milvus_read_with_retry("对话记忆召回", _search_memory)
    except Exception as e:
        LOGGER.error(f"Milvus 召回对话记忆失败: {e}")
        return []


def delete_chat_memory_by_conv(conversation_id: str) -> int:
    """删除指定会话的全部对话记忆向量。

    :return: 已删除条数, 失败返回 -1。
    """
    try:
        with _milvus_client() as client:
            _ensure_memory_collection(client)
            results = client.query(
                collection_name=_MEMORY_COLLECTION_NAME,
                filter=f'conversation_id == "{conversation_id}"',
                output_fields=["id"],
            )
            pks = [r["id"] for r in results]
            if pks:
                client.delete(collection_name=_MEMORY_COLLECTION_NAME, pks=pks)
            return len(pks)
    except Exception as e:
        LOGGER.error(f"Milvus 删除对话记忆失败: {e}")
        return -1


# ---------------------------------------------------------------------------
# 查询经验集合（采纳反馈与映射检索范围）——不改动 rag_chunks schema
# ---------------------------------------------------------------------------
_QUERY_MEMORY_COLLECTION_NAME = "rag_query_memory"
_QUERY_MEMORY_MAX_SOURCE_TYPE_BYTES = 32
_QUERY_MEMORY_MAX_SOURCE_ID_BYTES = 128
_QUERY_MEMORY_MAX_QUERY_BYTES = 8192
_QUERY_MEMORY_MAX_CANONICAL_BYTES = 8192
_QUERY_MEMORY_MAX_SCOPE_BYTES = 255
_query_memory_collection_ready: bool = False


def _ensure_query_memory_collection(client: MilvusClient) -> None:  # type: ignore
    """创建并加载独立查询经验集合；集合存在时只加载，不重建 schema。"""
    global _query_memory_collection_ready
    if _query_memory_collection_ready:
        try:
            client.load_collection(_QUERY_MEMORY_COLLECTION_NAME)
        except Exception:
            pass
        return

    if client.has_collection(_QUERY_MEMORY_COLLECTION_NAME):
        client.load_collection(_QUERY_MEMORY_COLLECTION_NAME)
        _query_memory_collection_ready = True
        return

    schema = CollectionSchema(
        fields=[
            FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=256, is_primary=True),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=PROJECT_CONFIG.EMBEDDING_DIM),
            FieldSchema(name="source_type", dtype=DataType.VARCHAR, max_length=_QUERY_MEMORY_MAX_SOURCE_TYPE_BYTES),
            FieldSchema(name="source_id", dtype=DataType.VARCHAR, max_length=_QUERY_MEMORY_MAX_SOURCE_ID_BYTES),
            FieldSchema(name="query_text", dtype=DataType.VARCHAR, max_length=_QUERY_MEMORY_MAX_QUERY_BYTES),
            FieldSchema(name="canonical_query", dtype=DataType.VARCHAR, max_length=_QUERY_MEMORY_MAX_CANONICAL_BYTES),
            FieldSchema(name="scope", dtype=DataType.VARCHAR, max_length=_QUERY_MEMORY_MAX_SCOPE_BYTES),
            FieldSchema(name="created_at", dtype=DataType.INT64),
        ],
        enable_dynamic_field=False,
    )
    try:
        client.create_collection(collection_name=_QUERY_MEMORY_COLLECTION_NAME, schema=schema)
    except Exception as create_err:
        if client.has_collection(_QUERY_MEMORY_COLLECTION_NAME):
            LOGGER.info(f"查询经验集合已由其他进程创建, 直接加载: {create_err}")
            client.load_collection(_QUERY_MEMORY_COLLECTION_NAME)
            _query_memory_collection_ready = True
            return
        raise

    from pymilvus.milvus_client.index import IndexParams

    vector_index = IndexParams()
    vector_index.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_index(collection_name=_QUERY_MEMORY_COLLECTION_NAME, index_params=vector_index)
    for field_name in ("source_type", "source_id", "scope"):
        try:
            scalar_index = IndexParams()
            scalar_index.add_index(field_name=field_name, index_type="INVERTED")
            client.create_index(collection_name=_QUERY_MEMORY_COLLECTION_NAME, index_params=scalar_index)
        except Exception:
            # 标量索引只用于加速过滤，不能阻断集合可用性。
            pass
    client.load_collection(_QUERY_MEMORY_COLLECTION_NAME)
    _query_memory_collection_ready = True


def ensure_query_memory_collection() -> bool:
    """确保查询经验集合可用；返回是否完成初始化。"""
    try:
        with _milvus_client() as client:
            _ensure_query_memory_collection(client)
        return True
    except Exception as e:
        LOGGER.error(f"初始化查询经验集合失败: {e}")
        return False


def upsert_query_memory(records: List[Dict[str, Any]]) -> int:
    """写入或更新查询经验；同一 id 重复写入结果一致。"""
    if not records:
        return 0
    now = int(time.time())
    rows = []
    for record in records:
        rows.append({
            "id": str(record["id"]),
            "vector": record.get("vector", []),
            "source_type": _truncate_bytes(str(record.get("source_type", "")), _QUERY_MEMORY_MAX_SOURCE_TYPE_BYTES),
            "source_id": _truncate_bytes(str(record.get("source_id", "")), _QUERY_MEMORY_MAX_SOURCE_ID_BYTES),
            "query_text": _truncate_bytes(str(record.get("query_text", "")), _QUERY_MEMORY_MAX_QUERY_BYTES),
            "canonical_query": _truncate_bytes(str(record.get("canonical_query", "")), _QUERY_MEMORY_MAX_CANONICAL_BYTES),
            "scope": _truncate_bytes(str(record.get("scope", "")), _QUERY_MEMORY_MAX_SCOPE_BYTES),
            "created_at": int(record.get("created_at") or now),
        })
    with _milvus_client() as client:
        _ensure_query_memory_collection(client)
        client.upsert(collection_name=_QUERY_MEMORY_COLLECTION_NAME, data=rows)
    return len(rows)


def search_query_memory(
        query_vectors: List[List[float]],
        top_k: int = 5,
        source_types: Optional[List[str]] = None,
        scope: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """按向量召回查询经验；返回结果后仍需回查 MySQL 校验有效性。"""
    if not query_vectors:
        return []
    def _search_memory(client: Any) -> List[Dict[str, Any]]:
        _ensure_query_memory_collection(client)
        filters = []
        if source_types:
            values = ", ".join('"' + str(value).replace('"', '\\"') + '"' for value in source_types)
            filters.append(f"source_type in [{values}]")
        if scope:
            filters.append(f'scope == "{str(scope).replace(chr(34), chr(92)+chr(34))}"')
        search_kwargs = {
            "collection_name": _QUERY_MEMORY_COLLECTION_NAME,
            "data": query_vectors,
            "limit": max(1, int(top_k)),
            "output_fields": ["source_type", "source_id", "query_text", "canonical_query", "scope", "created_at"],
            "search_params": {"metric_type": "COSINE"},
        }
        if filters:
            search_kwargs["filter"] = " and ".join(filters)
        results = client.search(**search_kwargs)
        hits = results[0] if results else []
        return [
            {
                **(_hit_value(hit, "entity", {}) or {}),
                "id": _normalize_primary_key(_hit_value(hit, "id")),
                "distance": _hit_value(hit, "distance"),
            }
            for hit in hits
        ]

    try:
        return _run_milvus_read_with_retry("查询经验召回", _search_memory)
    except Exception as e:
        LOGGER.error(f"Milvus 查询经验召回失败: {e}")
        return []


def delete_query_memory(ids: Optional[List[str]] = None, source_type: Optional[str] = None,
                        source_id: Optional[str] = None) -> int:
    """删除查询经验；支持按主键或来源定位，返回删除候选数量。"""
    if not ids and not (source_type and source_id):
        return 0
    try:
        with _milvus_client() as client:
            _ensure_query_memory_collection(client)
            if ids:
                result = client.delete(collection_name=_QUERY_MEMORY_COLLECTION_NAME, pks=[str(item) for item in ids])
                return int(result.get("delete_count", len(ids))) if isinstance(result, dict) else len(ids)
            escaped_type = str(source_type).replace('"', '\\"')
            escaped_id = str(source_id).replace('"', '\\"')
            result = client.delete(
                collection_name=_QUERY_MEMORY_COLLECTION_NAME,
                filter=f'source_type == "{escaped_type}" and source_id == "{escaped_id}"',
            )
            return int(result.get("delete_count", 0)) if isinstance(result, dict) else 0
    except Exception as e:
        LOGGER.error(f"Milvus 删除查询经验失败: {e}")
        return -1


def get_query_memory_stats() -> Dict[str, Any]:
    """返回查询经验集合统计；Milvus 不可用时返回明确的 empty 状态。"""
    try:
        with _milvus_client() as client:
            _ensure_query_memory_collection(client)
            stats = client.get_collection_stats(_QUERY_MEMORY_COLLECTION_NAME)
            return {"collection": _QUERY_MEMORY_COLLECTION_NAME, "row_count": int(stats.get("row_count", 0)), "status": "ok", "backend": "milvus"}
    except Exception as e:
        LOGGER.error(f"Milvus 查询经验统计失败: {e}")
        return {"collection": _QUERY_MEMORY_COLLECTION_NAME, "row_count": 0, "status": "empty", "backend": "milvus"}
