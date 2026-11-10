# -*- coding: utf-8 -*-
"""Milvus Server 持久化向量存储与内置 BM25 混合检索。"""

import hashlib
import json
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, TypeVar

# 尝试导入 pymilvus；milvus 后端为可选依赖，仅在使用该后端时需要安装
try:
    from pymilvus import (  # type: ignore
        CollectionSchema,
        DataType,
        FieldSchema,
        Function,
        FunctionType,
        MilvusClient,
        AnnSearchRequest,
        RRFRanker,
    )
    _HAS_PYMILVUS = True
except ImportError:
    _HAS_PYMILVUS = False
    MilvusClient = None  # type: ignore

from configure import LOGGER, PROJECT_CONFIG
from applications.knowledge_base.processing.milvus_pool import get_milvus_client_pool
from applications.knowledge_base.rag.section_context import SECTION_METADATA_KEYS

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
_COLLECTION_NAME = "rag_chunks"
_T = TypeVar("_T")


def _is_transient_milvus_error(exc: Exception) -> bool:
    """识别适合立即换连接重试一次的 Milvus/gRPC 短暂故障。"""
    message = f"{type(exc).__name__}: {exc}".casefold()
    return any(marker in message for marker in (
        "closed channel",
        "channel closed",
        "transport is closing",
        "failed to connect",
        "connection refused",
        "socket closed",
        "statuscode.unavailable",
        "statuscode.deadline_exceeded",
    ))


def _run_milvus_read_with_retry(
        operation_name: str,
        operation: Callable[[Any], _T],
) -> _T:
    """执行只读或幂等 Milvus 操作；连接类故障时换连接重试一次。"""
    for attempt in range(2):
        try:
            with _milvus_client() as client:
                return operation(client)
        except Exception as exc:
            if attempt == 0 and _is_transient_milvus_error(exc):
                LOGGER.warning(
                    f"Milvus {operation_name} 遇到短暂连接故障，换连接重试一次: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            raise
    raise RuntimeError(f"Milvus {operation_name} 重试流程异常结束")


def is_remote_milvus_uri(uri: str | None = None) -> bool:
    """判断 URI 是否为独立 Milvus Server 地址。"""
    value = str(uri if uri is not None else PROJECT_CONFIG.MILVUS_URI).strip().lower()
    return value.startswith(("http://", "https://"))

# VARCHAR 最大字节长度（Milvus 上限为 65535 字节）
_MAX_CONTENT_BYTES = 65535
_MAX_FILE_PATH_BYTES = 1024
_MAX_FILE_NAME_BYTES = 512
_MAX_DOC_ID_BYTES = 256
_MAX_MODALITY_BYTES = 64
_MAX_LANGUAGE_BYTES = 8

# 每个分块按 language 字段选择 analyzer；技术型混合文本使用 Jieba 兜底，
# 同时保留中文、拉丁字母、数字和连字符标识，并统一英文大小写。
_MULTI_ANALYZER_PARAMS: Dict[str, Any] = {
    "analyzers": {
        "chinese": {
            "tokenizer": "jieba",
            "filter": ["cnalphanumonly", "lowercase"],
        },
        "english": {"type": "english"},
        "default": {
            "tokenizer": "jieba",
            "filter": ["cnalphanumonly", "lowercase"],
        },
    },
    "by_field": "language",
    "alias": {"cn": "chinese", "en": "english", "mixed": "default"},
}

# ---------------------------------------------------------------------------
# 客户端管理（每次操作短连接）
# ---------------------------------------------------------------------------
_collection_ready: bool = False


def _hit_value(hit: Any, key: str, default: Any = None) -> Any:
    """兼容 MilvusClient 返回的 dict、Hit 和 NamedTuple 结果。"""
    if isinstance(hit, dict):
        return hit.get(key, default)
    try:
        return hit[key]
    except (KeyError, IndexError, TypeError, AttributeError):
        return getattr(hit, key, default)


def _normalize_primary_key(value: Any) -> str:
    """把 Milvus 的 int/str/numpy 标量主键统一成可序列化字符串。

    旧版 pymilvus 在 hybrid_search 中可能返回 numpy 标量或 Hit 对象；
    直接把这类对象传给下游重排、JSON 或删除接口会触发 ``unsupported ID
    type``。当前 rag_chunks 的新 schema 主键是 VARCHAR，因此统一转成 str。
    """
    if value is None:
        return ""
    try:
        return str(value.item())
    except AttributeError:
        return str(value)


@contextmanager
def _milvus_client() -> Iterator[MilvusClient]:  # type: ignore
    """按操作创建 Milvus Server 短连接，用完即关闭。"""
    if not _HAS_PYMILVUS:
        raise ImportError(
            "pymilvus 未安装, 请执行: pip install pymilvus==2.6.4"
        )
    if not is_remote_milvus_uri():
        raise ValueError(
            "仅支持 Milvus C/S 架构；MILVUS_URI 必须是 http:// 或 https:// 服务端地址"
        )

    # 配置 gRPC 保活，降低长时间解析/嵌入后复用连接时被服务端断开的概率。
    import os as _os
    _os.environ.setdefault("GRPC_ARG_KEEPALIVE_TIME_MS", "120000")
    _os.environ.setdefault("GRPC_ARG_KEEPALIVE_TIMEOUT_MS", "30000")
    _os.environ.setdefault("GRPC_ARG_KEEPALIVE_PERMIT_WITHOUT_CALLS", "1")
    _os.environ.setdefault("GRPC_ARG_HTTP2_MIN_RECV_PING_INTERVAL_WITHOUT_DATA_MS", "60000")

    pool = get_milvus_client_pool(
        uri=PROJECT_CONFIG.MILVUS_URI,
        user=PROJECT_CONFIG.MILVUS_USER or "",
        password=PROJECT_CONFIG.MILVUS_PASSWORD or "",
        token=PROJECT_CONFIG.MILVUS_TOKEN or "",
        max_size=PROJECT_CONFIG.MILVUS_POOL_SIZE,
        acquire_timeout=PROJECT_CONFIG.MILVUS_POOL_ACQUIRE_TIMEOUT,
        client_cls=MilvusClient,
    )
    with pool.connection() as client:
        yield client


def _ensure_collection(client: MilvusClient) -> None:  # type: ignore
    """集合与索引不存在时创建，随后加载（接口设计参考 LightRAG）。"""
    global _collection_ready
    if _collection_ready:
        # 短连接模式下每个新客户端都确保集合已经加载。
        try:
            client.load_collection(_COLLECTION_NAME)
        except Exception:
            pass
        return

    if client.has_collection(_COLLECTION_NAME):
        _verify_collection_schema(client)
        client.load_collection(_COLLECTION_NAME)
        _collection_ready = True
        return

    # 创建 schema
    schema = CollectionSchema(
        fields=[
            FieldSchema(
                name="id",
                dtype=DataType.VARCHAR,
                max_length=256,
                is_primary=True,
            ),
            FieldSchema(
                name="vector",
                dtype=DataType.FLOAT_VECTOR,
                dim=PROJECT_CONFIG.EMBEDDING_DIM,
            ),
            FieldSchema(
                name="created_at",
                dtype=DataType.INT64,
            ),
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                max_length=_MAX_CONTENT_BYTES,
            ),
            FieldSchema(
                name="language",
                dtype=DataType.VARCHAR,
                max_length=_MAX_LANGUAGE_BYTES,
            ),
            FieldSchema(
                name="search_text",
                dtype=DataType.VARCHAR,
                max_length=_MAX_CONTENT_BYTES,
                enable_analyzer=True,
                multi_analyzer_params=_MULTI_ANALYZER_PARAMS,
            ),
            FieldSchema(
                name="sparse_vector",
                dtype=DataType.SPARSE_FLOAT_VECTOR,
            ),
            FieldSchema(
                name="file_path",
                dtype=DataType.VARCHAR,
                max_length=_MAX_FILE_PATH_BYTES,
            ),
            FieldSchema(
                name="file_name",
                dtype=DataType.VARCHAR,
                max_length=_MAX_FILE_NAME_BYTES,
            ),
            FieldSchema(
                name="doc_id",
                dtype=DataType.VARCHAR,
                max_length=_MAX_DOC_ID_BYTES,
            ),
            FieldSchema(
                name="tokens",
                dtype=DataType.INT64,
            ),
            FieldSchema(
                name="modality",
                dtype=DataType.VARCHAR,
                max_length=_MAX_MODALITY_BYTES,
            ),
            FieldSchema(
                name="chunk_order_index",
                dtype=DataType.INT64,
            ),
        ],
        enable_dynamic_field=True,
    )
    schema.add_function(
        Function(
            name="search_text_bm25",
            function_type=FunctionType.BM25,
            input_field_names=["search_text"],
            output_field_names=["sparse_vector"],
        )
    )

    try:
        client.create_collection(collection_name=_COLLECTION_NAME, schema=schema)
    except Exception as create_err:
        # 多进程首次写入时可能并发建集合；仅在另一进程已经创建成功时接管。
        if client.has_collection(_COLLECTION_NAME):
            LOGGER.info(f"集合已由其他进程创建, 直接加载: {create_err}")
            _verify_collection_schema(client)
            client.load_collection(_COLLECTION_NAME)
            _collection_ready = True
            return
        raise

    # 创建向量索引
    from pymilvus.milvus_client.index import IndexParams

    _v_idx = IndexParams()
    _v_idx.add_index(
        field_name="vector", index_type="AUTOINDEX",
        metric_type="COSINE",
    )
    client.create_index(collection_name=_COLLECTION_NAME, index_params=_v_idx)

    _bm25_idx = IndexParams()
    _bm25_idx.add_index(
        field_name="sparse_vector",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={"inverted_index_algo": "DAAT_MAXSCORE"},
    )
    client.create_index(collection_name=_COLLECTION_NAME, index_params=_bm25_idx)

    # 为 doc_id 创建标量索引，加速按文档删除
    try:
        _s_idx = IndexParams()
        _s_idx.add_index(field_name="doc_id", index_type="INVERTED")
        client.create_index(collection_name=_COLLECTION_NAME, index_params=_s_idx)
    except Exception:
        pass  # 标量索引仅为性能优化，并非必需

    client.load_collection(_COLLECTION_NAME)
    _collection_ready = True


# ---------------------------------------------------------------------------
# 截断保护
# ---------------------------------------------------------------------------
def _verify_collection_schema(client: MilvusClient) -> None:  # type: ignore
    """校验已有集合具备当前维度、BM25 字段和 analyzer schema。

    维度不一致（更换嵌入模型 / 改过配置）会使后续全部 upsert 失败——
    前置校验把"流水线最后一步才失败"变成秒级失败。仅在进程内首次
    确认集合存在时调用一次（_collection_ready 置位后不再进入本分支）。

    pymilvus 各版本 describe 返回结构略有差异: 解析不出维度时跳过
    校验（upsert 时仍会自然报错）, 校验本身不阻塞主流程。
    """
    try:
        desc = client.describe_collection(_COLLECTION_NAME)
        fields = {field.get("name"): field for field in desc.get("fields", [])}
        required = {"id", "vector", "content", "language", "search_text", "sparse_vector"}
        missing = sorted(required - set(fields))
        if missing:
            raise RuntimeError(
                f"Milvus 集合 {_COLLECTION_NAME} 是旧 schema，缺少字段: {', '.join(missing)}。"
                "当前版本不做迁移，请删除该集合后重新解析文档"
            )
        for field in fields.values():
            if field.get("name") != "vector":
                continue
            dim = field.get("dim") or (field.get("params") or {}).get("dim")
            if dim is not None and int(dim) != PROJECT_CONFIG.EMBEDDING_DIM:
                raise RuntimeError(
                    f"向量库集合维度 ({dim}) 与配置 EMBEDDING_DIM "
                    f"({PROJECT_CONFIG.EMBEDDING_DIM}) 不一致: 通常因更换嵌入模型"
                    f"或修改维度配置而未重建集合。请修正配置与集合一致, "
                    f"或清空集合后重新上传全部文档"
                )
            return
    except RuntimeError:
        raise  # 维度不一致是确定性配置错误, 必须上抛
    except Exception as e:
        LOGGER.debug(f"集合 schema 校验跳过（describe 未取到字段信息）: {e}")


def _truncate_bytes(value: str, max_bytes: int) -> str:
    """将字符串截断到 *max_bytes* 个 UTF-8 字节以内。"""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    # 逐字节回退，直到落在合法的 UTF-8 边界上
    while max_bytes > 0:
        try:
            return encoded[:max_bytes].decode("utf-8")
        except UnicodeDecodeError:
            max_bytes -= 1
    return ""


# ---------------------------------------------------------------------------
# 文本规范化与公共 API
# ---------------------------------------------------------------------------

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TECH_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:/-]{2,}")
_TABLE_ROW_ORDINAL_RE = re.compile(
    r"第\s*\d+\s*行(?:\s*/\s*共\s*\d+\s*行|中)?"
)


def _detect_language(text: str) -> str:
    """按字符比例判定分块主语言；技术标识不会被当作中文或英文句子。"""
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    total = cjk + latin
    if total == 0:
        return "mixed"
    ratio = cjk / total
    if cjk and latin and 0.15 <= ratio <= 0.85:
        return "mixed"
    return "cn" if ratio > 0.5 else "en"


def _build_search_text(content: str) -> str:
    """保留原文并追加技术词规范化变体，提升字段名/编号的 BM25 召回。

    例如 ``responseCode`` 追加 ``response Code``，``ISO-8583`` 追加
    ``ISO8583`` 与 ``ISO 8583``。原文不被改写，引用仍使用 content 字段。
    """
    # 解析器生成的行序号用于展示溯源，不是业务词项。否则查询代码值 11 时，
    # 大量“第 11 行”的无关表格行会在 BM25 中获得虚假精确匹配。
    searchable_content = _TABLE_ROW_ORDINAL_RE.sub("表格行", content)
    variants: List[str] = []
    seen = set()
    for token in _TECH_TOKEN_RE.findall(searchable_content):
        candidates = [
            _CAMEL_BOUNDARY_RE.sub(" ", token),
            re.sub(r"[_.:/-]+", "", token),
            re.sub(r"[_.:/-]+", " ", token),
        ]
        for value in candidates:
            value = " ".join(value.split())
            key = value.casefold()
            if value and value != token and key not in seen:
                seen.add(key)
                variants.append(value)
    if not variants:
        return searchable_content
    return f"{searchable_content}\n{' '.join(variants)}"

def upsert_chunks(
        chunks: List[Dict[str, Any]],
        file_path: str = "",
        doc_id: str = "",
) -> int:
    """向 Milvus 插入或更新分块向量（接口设计参考 LightRAG）。

    :param chunks: 分块字典列表，每个元素必须包含 ``content`` 与 ``vector``。
    :param file_path: 源文档路径（用于引用溯源）。
    :param doc_id: 文档唯一标识。
    :return: 已存储的分块数量。
    """
    if not chunks:
        return 0

    file_name = Path(file_path).name if file_path else ""
    now = int(time.time())

    records: List[Dict[str, Any]] = []
    for i, c in enumerate(chunks):
        order_index = int(c.get("chunk_order_index", i) or 0)
        chunk_id = str(c.get("id") or c.get("chunk_id") or (
            f"{doc_id}-chunk-{order_index:04d}" if doc_id else f"chunk-{order_index:04d}"
        ))
        vec = c.get("vector", [])
        content = c.get("content", "")
        language = c.get("language") or _detect_language(content)
        if language not in {"cn", "en", "mixed"}:
            language = "mixed"
        search_text = c.get("search_text") or _build_search_text(content)
        records.append({
            "id": chunk_id,
            "vector": vec,
            "created_at": now,
            "content": _truncate_bytes(content, _MAX_CONTENT_BYTES),
            "language": language,
            "search_text": _truncate_bytes(search_text, _MAX_CONTENT_BYTES),
            "file_path": _truncate_bytes(file_path, _MAX_FILE_PATH_BYTES),
            "file_name": _truncate_bytes(file_name, _MAX_FILE_NAME_BYTES),
            "doc_id": _truncate_bytes(doc_id, _MAX_DOC_ID_BYTES),
            "tokens": c.get("tokens", 0),
            "modality": _truncate_bytes(
                c.get("modality", "text"), _MAX_MODALITY_BYTES
            ),
            "chunk_order_index": order_index,
        })
        # 集合启用了 dynamic field；表格结构元数据保留在记录中，供代码值
        # 精确检索、审计和后续扩展使用。普通文本块不写这些键。
        for key in ("table_name", "field_no", "code_value", "page_no", "source_filename"):
            value = c.get(key)
            if value not in (None, ""):
                records[-1][key] = value
        records[-1].update({key: c[key] for key in SECTION_METADATA_KEYS if key in c})

    with _milvus_client() as client:
        _ensure_collection(client)
        # 分批写入: 数千分块 × 1024 维一次性 upsert 的 payload 可达数十 MB,
        # 可能触及 gRPC 消息上限导致整篇文档在流水线最后一步失败。
        # 块 ID 幂等, 某批失败后由管道标 failed, 重试整篇写入安全
        batch_size = max(1, PROJECT_CONFIG.VECTOR_UPSERT_BATCH_SIZE)
        for start in range(0, len(records), batch_size):
            client.upsert(
                collection_name=_COLLECTION_NAME,
                data=records[start:start + batch_size],
            )
    return len(records)


def _search_chunks(
        client: Any,
        query_vectors: List[List[float]],
        top_k: int,
        filter_expr: str = "",
) -> List[Dict[str, Any]]:
    """向量检索内部实现（可选标量过滤）, 返回统一分块字典格式。"""
    _ensure_collection(client)

    output_fields = [
        "id", "content", "file_path", "file_name",
        "doc_id", "tokens", "modality", "chunk_order_index",
        "created_at", *SECTION_METADATA_KEYS,
    ]

    search_kwargs: Dict[str, Any] = {
        "collection_name": _COLLECTION_NAME,
        "data": query_vectors,  # Milvus 期望传入向量列表; 单个查询向量也需包装成列表
        # rag_chunks 同时包含 dense vector 与 BM25 sparse_vector。Milvus 2.6
        # 在多向量字段集合中不会猜测目标字段，必须显式指定 dense 字段。
        "anns_field": "vector",
        "limit": top_k,
        "output_fields": output_fields,
        "search_params": {"metric_type": "COSINE", "params": {}},
    }
    if filter_expr:
        search_kwargs["filter"] = filter_expr
    results = client.search(**search_kwargs)

    # Milvus 返回 list[SearchResult]；展开第一个查询的结果
    if not results:
        return []

    hits = results[0]
    chunks: List[Dict[str, Any]] = []
    for hit in hits:
        entity = _hit_value(hit, "entity", {}) or {}
        hit_id = _normalize_primary_key(_hit_value(hit, "id"))
        chunks.append({
            "id": hit_id,
            "chunk_id": hit_id,
            "content": _hit_value(entity, "content", ""),
            "file_path": _hit_value(entity, "file_path", "unknown_source"),
            "file_name": _hit_value(entity, "file_name", ""),
            "doc_id": _hit_value(entity, "doc_id", ""),
            "tokens": _hit_value(entity, "tokens", 0),
            "modality": _hit_value(entity, "modality", "text"),
            "order": _hit_value(entity, "chunk_order_index", 0),
            "distance": _hit_value(hit, "distance", None),
            "created_at": _hit_value(entity, "created_at"),
            **{key: _hit_value(entity, key) for key in SECTION_METADATA_KEYS
               if _hit_value(entity, key) is not None},
        })
    return chunks


def hybrid_query_chunks(
        query_vectors: List[List[float]],
        chinese_query: str,
        english_query: str = "",
        *,
        top_k: int = 100,
        dense_top_k: int = 60,
        bm25_top_k: int = 60,
        filter_expr: str = "",
        diagnostics: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """使用 Milvus 内置 BM25 + Dense + RRF 执行中英双语混合检索。"""
    if not query_vectors or not chinese_query.strip():
        if diagnostics is not None:
            diagnostics.update(mode="skipped", reason="empty_search_input")
        return []

    rrf_k = 60
    if diagnostics is not None:
        diagnostics.update(mode="hybrid_rrf", rrf_k=rrf_k)
    output_fields = [
        "id", "content", "file_path", "file_name", "doc_id", "tokens",
        "modality", "chunk_order_index", "created_at", "language", *SECTION_METADATA_KEYS,
    ]
    expr = filter_expr or None
    requests = [
        AnnSearchRequest(
            data=query_vectors,
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {}},
            limit=dense_top_k,
            expr=expr,
        ),
        AnnSearchRequest(
            data=[chinese_query.strip()],
            anns_field="sparse_vector",
            param={
                "metric_type": "BM25",
                "params": {"drop_ratio_search": 0.1},
                "analyzer_name": "cn",
            },
            limit=bm25_top_k,
            expr=expr,
        ),
    ]
    english_query = english_query.strip()
    if english_query and english_query.casefold() != chinese_query.strip().casefold():
        requests.append(
            AnnSearchRequest(
                data=[english_query],
                anns_field="sparse_vector",
                param={
                    "metric_type": "BM25",
                    "params": {"drop_ratio_search": 0.1},
                    "analyzer_name": "en",
                },
                limit=bm25_top_k,
                expr=expr,
            )
        )

    def _hybrid_search(client: Any) -> Any:
        _ensure_collection(client)
        # Milvus 2.6 在空集合上执行 hybrid_search 可能返回服务端
        # ``unsupported ID type``，而不是空结果。先做一次轻量主键探测，
        # 将空集合稳定地视为无召回，避免把正常的冷启动误报成 ID 错误。
        try:
            if not client.query(
                collection_name=_COLLECTION_NAME,
                filter="id != ''",
                output_fields=["id"],
                limit=1,
            ):
                return []
        except Exception:
            # 探测接口在部分旧版服务不可用时，继续让 hybrid_search
            # 执行；真正的检索错误仍由下方统一捕获并降级。
            pass
        return client.hybrid_search(
            collection_name=_COLLECTION_NAME,
            reqs=requests,
            ranker=RRFRanker(rrf_k),
            limit=top_k,
            output_fields=output_fields,
        )

    try:
        results = _run_milvus_read_with_retry("混合检索", _hybrid_search)
    except Exception as exc:
        LOGGER.error(f"Milvus 混合检索失败: {type(exc).__name__}: {exc}")
        if diagnostics is not None:
            diagnostics.update(mode="dense_fallback", fallback_reason="hybrid_search_error",
                               hybrid_error_type=type(exc).__name__)
        # 部分 Milvus 版本在 BM25 分路无命中、而 Dense 分路有命中时，
        # hybrid_search 会错误返回 ``unsupported ID type``。不能因此把
        # 整个问题判定为“无召回”：退回同一查询的 Dense 结果，后续仍由
        # RRF 外层和 rerank 统一排序。
        try:
            fallback = _run_milvus_read_with_retry(
                "混合检索向量回退",
                lambda fallback_client: _search_chunks(
                    fallback_client, query_vectors, top_k, filter_expr=filter_expr),
            )
            for chunk in fallback:
                chunk["source"] = "milvus_dense_fallback"
            return fallback
        except Exception as fallback_exc:
            if diagnostics is not None:
                diagnostics.update(mode="failed", reason="dense_fallback_error",
                                   dense_error_type=type(fallback_exc).__name__)
            LOGGER.error(
                f"Milvus Dense 兜底检索也失败: "
                f"{type(fallback_exc).__name__}: {fallback_exc}"
            )
            return []

    if not results:
        return []
    chunks: List[Dict[str, Any]] = []
    for hit in results[0]:
        entity = _hit_value(hit, "entity", {}) or {}
        hit_id = _normalize_primary_key(_hit_value(hit, "id"))
        chunks.append({
            "id": hit_id,
            "chunk_id": hit_id,
            "content": _hit_value(entity, "content", ""),
            "file_path": _hit_value(entity, "file_path", "unknown_source"),
            "file_name": _hit_value(entity, "file_name", ""),
            "doc_id": _hit_value(entity, "doc_id", ""),
            "tokens": _hit_value(entity, "tokens", 0),
            "modality": _hit_value(entity, "modality", "text"),
            "order": _hit_value(entity, "chunk_order_index", 0),
            "distance": _hit_value(hit, "distance", None),
            "created_at": _hit_value(entity, "created_at"),
            "language": _hit_value(entity, "language", "mixed"),
            "source": "milvus_hybrid",
            **{key: _hit_value(entity, key) for key in SECTION_METADATA_KEYS
               if _hit_value(entity, key) is not None},
        })
    return chunks


def query_chunks(
        query_vectors: List[List[float]], top_k: int = 60
) -> List[Dict[str, Any]]:
    """按向量相似度从 Milvus 检索分块（接口设计参考 LightRAG）。

    :param query_vectors: 一个或多个查询向量。
    :param top_k: 返回的结果数量上限。
    :return: 统一格式的分块字典列表：
        ``id``、``chunk_id``、``content``、``file_path``、``file_name``、``doc_id``、
        ``tokens``、``modality``、``order``、``distance``、``created_at``。
    """
    try:
        return _run_milvus_read_with_retry(
            "向量检索",
            lambda client: _search_chunks(client, query_vectors, top_k),
        )
    except Exception as e:
        LOGGER.error(f"Milvus 查询分块失败: {e}")
        return []


def query_chunks_by_doc(
        query_vectors: List[List[float]], doc_id: str, top_k: int = 8
) -> List[Dict[str, Any]]:
    """在指定文档范围内按向量相似度检索分块（文档级召回的定向注入通道）。

    以标量过滤限定 doc_id（doc_id 上有倒排索引, 过滤开销可忽略）,
    返回格式与 query_chunks 完全一致。文档级召回命中某文档后, 用本函数
    定向取其 top 分块送入重排候选池——是否进最终窗口仍由重排阈值决定。
    """
    if not doc_id:
        return []
    try:
        return _run_milvus_read_with_retry(
            "文档范围检索",
            lambda client: _search_chunks(
                client, query_vectors, top_k, filter_expr=f'doc_id == "{doc_id}"'
            ),
        )
    except Exception as e:
        LOGGER.error(f"Milvus 按文档查询分块失败: doc_id={doc_id}, {e}")
        return []


def query_neighbor_chunks(
        anchors: List[Dict[str, Any]],
        window: int = 1,
        max_anchors: int = 16,
) -> List[Dict[str, Any]]:
    """读取候选分块在同一文档中的前后邻块。

    表格标题、表头和数据行经常跨分块；邻块只作为 rerank 的补充候选，
    不直接改变最终答案。按 ``doc_id + chunk_order_index`` 精确查询，避免
    对全库执行额外向量召回。
    """
    if window < 1 or not anchors:
        return []
    grouped: Dict[str, set] = {}
    for chunk in anchors[:max(1, max_anchors)]:
        doc_id = str(chunk.get("doc_id") or "").strip()
        try:
            order = int(chunk.get("order", chunk.get("chunk_order_index")))
        except (TypeError, ValueError):
            continue
        if not doc_id:
            continue
        orders = grouped.setdefault(doc_id, set())
        for candidate_order in range(max(0, order - window), order + window + 1):
            orders.add(candidate_order)
    if not grouped:
        return []

    output_fields = [
        "id", "content", "file_path", "file_name", "doc_id", "tokens",
        "modality", "chunk_order_index", "created_at", "language",
        "table_name", "field_no", "code_value", "page_no",
        *SECTION_METADATA_KEYS,
    ]
    def _query_neighbors(client: Any) -> List[Dict[str, Any]]:
        _ensure_collection(client)
        neighbors: List[Dict[str, Any]] = []
        for doc_id, orders in grouped.items():
            escaped_doc_id = doc_id.replace("\\", "\\\\").replace('"', '\\"')
            order_values = ",".join(str(value) for value in sorted(orders))
            rows = client.query(
                collection_name=_COLLECTION_NAME,
                filter=(
                    f'doc_id == "{escaped_doc_id}" and '
                    f'chunk_order_index in [{order_values}]'
                ),
                output_fields=output_fields,
                limit=max(1, len(orders)),
            )
            for row in rows:
                chunk_id = _normalize_primary_key(row.get("id"))
                neighbors.append({
                    "id": chunk_id,
                    "chunk_id": chunk_id,
                    "content": row.get("content", ""),
                    "file_path": row.get("file_path", "unknown_source"),
                    "file_name": row.get("file_name", ""),
                    "doc_id": row.get("doc_id", ""),
                    "tokens": row.get("tokens", 0),
                    "modality": row.get("modality", "text"),
                    "order": row.get("chunk_order_index", 0),
                    "distance": None,
                    "created_at": row.get("created_at"),
                    "language": row.get("language", "mixed"),
                    "table_name": row.get("table_name", ""),
                    "field_no": row.get("field_no", ""),
                    "code_value": row.get("code_value", ""),
                    "page_no": row.get("page_no"),
                    **{key: row[key] for key in SECTION_METADATA_KEYS if key in row},
                })
        return neighbors

    try:
        neighbors = _run_milvus_read_with_retry("相邻分块查询", _query_neighbors)
    except Exception as exc:
        LOGGER.warning(f"Milvus 相邻分块查询失败: {type(exc).__name__}: {exc}")
        return []
    neighbors.sort(key=lambda item: (str(item.get("doc_id") or ""), int(item.get("order") or 0)))
    return neighbors


def delete_by_doc_id(doc_id: str) -> int:
    """按文档过滤条件删除全部分块；保留异常供调用方分类和重试。

    不先查询全部主键，避免大文档触及 query 的默认条数/窗口上限。
    强一致性读取确认删除完成后才允许调用方清理文档记录。
    """
    if not doc_id:
        raise ValueError("doc_id 不能为空")
    expression = 'doc_id == ' + json.dumps(doc_id, ensure_ascii=False)

    def _delete(client: Any) -> int:
        if not client.has_collection(_COLLECTION_NAME, timeout=15):
            return 0
        result = client.delete(
            collection_name=_COLLECTION_NAME, filter=expression, timeout=15,
        )
        residue = client.query(
            collection_name=_COLLECTION_NAME, filter=expression,
            output_fields=["id"], limit=1, consistency_level="Strong", timeout=15,
        )
        if residue:
            raise RuntimeError(f"向量删除后仍有残留: doc_id={doc_id}")
        return int(result.get("delete_count", result.get("deleted_count", 0)))

    # 按 doc_id 的删除是幂等操作，连接关闭时可安全换连接重试。
    return _run_milvus_read_with_retry("删除文档分块", _delete)


def _query_collection_all(
        client: MilvusClient,
        collection_name: str,
        filter: str,
        output_fields: List[str],
        batch_size: int = 5000,
) -> List[Dict[str, Any]]:
    """通过 query_iterator 分批读取集合，兼容 Milvus 3 的 16384 窗口限制。"""
    iterator = client.query_iterator(
        collection_name=collection_name,
        filter=filter,
        output_fields=output_fields,
        batch_size=batch_size,
        limit=-1,
    )
    rows: List[Dict[str, Any]] = []
    try:
        while True:
            batch = iterator.next()
            if not batch:
                break
            rows.extend(batch)
    finally:
        close = getattr(iterator, "close", None)
        if close:
            close()
    return rows


def get_all_chunks() -> List[Dict[str, Any]]:
    """返回 Milvus 集合中存储的全部分块，供 BM25 建索引使用。"""
    try:
        with _milvus_client() as client:
            _ensure_collection(client)
            results = _query_collection_all(
                client,
                collection_name=_COLLECTION_NAME,
                filter="id != ''",
                output_fields=["id", "content", "file_path", "file_name", "doc_id", "tokens", "modality", "chunk_order_index", "content_headings", *SECTION_METADATA_KEYS],
            )
        return [
            {
                "id": _normalize_primary_key(r.get("id")),
                "content": r.get("content", ""),
                "file_path": r.get("file_path", ""),
                "file_name": r.get("file_name", ""),
                "doc_id": r.get("doc_id", ""),
                "tokens": r.get("tokens", 0),
                "modality": r.get("modality", "text"),
                "order": r.get("chunk_order_index", 0),
                "content_headings": r.get("content_headings", ""),
                **{key: r[key] for key in SECTION_METADATA_KEYS if key in r},
            }
            for r in results
        ]
    except Exception as e:
        LOGGER.error(f"Milvus 获取全部分块失败: {e}")
        return []


def get_collection_fingerprint() -> str:
    """分块 ID 集合 + 最新写入时间指纹（md5）: 供 Web 侧判断 BM25 索引是否需要重建。

    在 Worker 进程内计算（只查 ID 与 created_at 两列的轻量查询）, RPC 路径
    仅回传一个短字符串——替代原方案中"Web 每次查询都全量拉取全部分块正文
    来算指纹"的做法（稳态下每次查询的跨进程 payload 从数十 MB 降到字节级）。

    指纹 = md5(最大 created_at + 排序后 ID 集)。**必须包含 created_at**:
    块 ID 为 <doc_id>-chunk-NNNN 顺序编号, 文档增量更新若分块数不变,
    ID 集合完全不变——仅 ID 指纹永远探测不到内容更新, BM25 索引将永久
    停留在旧版本; 而 upsert 每次写入都刷新 created_at, 以其最大值入指纹
    即可感知任何一次重写。

    失败返回空串: Web 侧据此降级（有旧索引用旧索引, 冷启动则全量拉取）。
    """
    try:
        with _milvus_client() as client:
            _ensure_collection(client)
            results = _query_collection_all(
                client,
                collection_name=_COLLECTION_NAME,
                filter="id != ''",
                output_fields=["id", "created_at"],
            )
        ids = sorted(_normalize_primary_key(r.get("id")) for r in results)
        max_created = max((int(r.get("created_at") or 0) for r in results), default=0)
        return hashlib.md5(f"{max_created}|{'|'.join(ids)}".encode()).hexdigest()
    except Exception as e:
        LOGGER.error(f"Milvus 计算集合指纹失败: {e}")
        return ""


def list_collection_doc_ids() -> Optional[set]:
    """集合中现存的全部 doc_id（孤儿分块 GC 用, 与文档表对账）。

    :return: doc_id 集合; 查询失败返回 None（GC 必须跳过本轮——
        空集合与查询失败不可混淆, 否则会把全部文档误判为孤儿）。
    """
    try:
        with _milvus_client() as client:
            _ensure_collection(client)
            results = _query_collection_all(
                client,
                collection_name=_COLLECTION_NAME,
                filter="id != ''",
                output_fields=["doc_id"],
            )
        return {r.get("doc_id", "") for r in results if r.get("doc_id")}
    except Exception as e:
        LOGGER.error(f"Milvus 获取集合 doc_id 列表失败: {e}")
        return None


def get_collection_stats() -> Dict[str, Any]:
    """返回集合统计信息，用于监控。"""
    try:
        with _milvus_client() as client:
            _ensure_collection(client)
            stats = client.get_collection_stats(_COLLECTION_NAME)
        row_count = stats.get("row_count", 0) if isinstance(stats, dict) else 0
        return {
            "collection": _COLLECTION_NAME,
            "chunk_count": row_count,
            "status": "ok",
            "backend": "milvus",
        }
    except Exception as e:
        LOGGER.error(f"Milvus 获取集合统计失败: {e}")
        return {
            "collection": _COLLECTION_NAME,
            "chunk_count": 0,
            "status": "empty",
            "backend": "milvus",
        }


# ---------------------------------------------------------------------------
# 对话记忆集合（L4 向量回忆）——与文档分块集合 rag_chunks 相互独立
# ---------------------------------------------------------------------------
# 设计: 每个"问答轮次"一条向量, 以 conversation_id 隔离, 问答时按当前问题
# 召回本会话的旧轮次, 为超长对话提供精准的细节回忆。集合、维度与文档分块
# 共用 EMBEDDING_DIM（同一嵌入模型）。
_MEMORY_COLLECTION_NAME = "rag_chat_memory"

# VARCHAR 字节上限（Milvus 上限 65535, 预留余量）
_MEMORY_MAX_QUESTION_BYTES = 8192
_MEMORY_MAX_ANSWER_BYTES = 16384
_MEMORY_MAX_CONV_ID_BYTES = 64

_memory_collection_ready: bool = False
