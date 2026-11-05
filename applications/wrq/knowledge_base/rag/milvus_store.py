"""Read-only query adapters; ingestion continues to use the existing store."""
import json
from applications.knowledge_base.rag import milvus_store as store
from .scope import current_scope

def _filter(extra=''):
    base = 'doc_id in ' + json.dumps(sorted(current_scope.get()))
    return f'({base}) and ({extra})' if extra else base

def query_chunks(vectors, top_k=100):
    with store._milvus_client() as client:
        return store._search_chunks(client, vectors, top_k, filter_expr=_filter())

def hybrid_query_chunks(query_vectors, chinese_query, english_query='', **kwargs):
    # Use a restricted client even in the existing store's dense fallback.
    return _scoped_hybrid(query_vectors, chinese_query, english_query, **kwargs)

def _scoped_hybrid(query_vectors, chinese_query, english_query='', **kwargs):
    # Existing fallback also receives the full authorization expression.
    kwargs['filter_expr'] = _filter(kwargs.get('filter_expr', ''))
    return store.hybrid_query_chunks(query_vectors, chinese_query, english_query, **kwargs)

def query_chunks_by_doc(vectors, doc_id, top_k=8):
    if str(doc_id) not in current_scope.get():
        return []
    return store.query_chunks_by_doc(vectors, doc_id, top_k)

def query_neighbor_chunks(anchors, **kwargs):
    allowed = current_scope.get()
    return [c for c in store.query_neighbor_chunks(
        [a for a in anchors if str(a.get('doc_id')) in allowed], **kwargs)
        if str(c.get('doc_id')) in allowed]

def get_collection_stats():
    return dict(chunk_count=len(current_scope.get()), status='scoped')

from .memory_store import upsert_chat_memory, search_chat_memory, search_query_memory
