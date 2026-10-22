# -*- coding: utf-8 -*-
"""ChromaDB 本地向量存储"""

import uuid
from typing import List

import chromadb
from chromadb.config import Settings

from configure import PROJECT_CONFIG, LOGGER


class ChromaStore:
    """Chroma 持久化向量库（本地模式）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_client"):
            PROJECT_CONFIG.chroma_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(PROJECT_CONFIG.chroma_path),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=PROJECT_CONFIG.CHROMA_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
            LOGGER.info(f"[Chroma] 本地向量库: {PROJECT_CONFIG.chroma_path}")

    def upsert_chunks(self, kb_id: str, chunks: List[dict]) -> List[str]:
        """批量写入向量，返回 Chroma 文档 ID 列表"""
        if not chunks:
            return []

        ids = []
        embeddings = []
        documents = []
        metadatas = []

        for chunk in chunks:
            vector_id = chunk.get("vector_id") or str(uuid.uuid4())
            ids.append(vector_id)
            embeddings.append(chunk["embedding"])
            documents.append(chunk["content"])
            metadata = {
                "kb_id": kb_id,
                "doc_id": chunk["doc_id"],
                "chunk_id": chunk["chunk_id"],
            }
            if chunk.get("page_number") is not None:
                metadata["page_number"] = chunk["page_number"]
            if chunk.get("filename"):
                metadata["filename"] = chunk["filename"]
            if chunk.get("embedding_model"):
                metadata["embedding_model"] = chunk["embedding_model"]
            metadatas.append(metadata)

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        return ids

    def search(
            self,
            knowledge_base_ids: List[str],
            query_embedding: List[float],
            top_k: int = None,
    ) -> List[dict]:
        """按知识库过滤的相似度检索"""
        if not knowledge_base_ids:
            return []

        top_k = top_k or PROJECT_CONFIG.RETRIEVAL_TOP_K

        where = (
            {"kb_id": {"$in": knowledge_base_ids}}
            if len(knowledge_base_ids) > 1
            else {"kb_id": knowledge_base_ids[0]}
        )

        result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        if not result["ids"] or not result["ids"][0]:
            return hits

        for i, doc_id in enumerate(result["ids"][0]):
            metadata = result["metadatas"][0][i] or {}
            distance = result["distances"][0][i] if result["distances"] else 0.0
            page_number = metadata.get("page_number")
            if page_number is not None:
                page_number = int(page_number)
            hits.append(
                {
                    "id": doc_id,
                    "kb_id": metadata.get("kb_id", ""),
                    "doc_id": metadata.get("doc_id", ""),
                    "chunk_id": metadata.get("chunk_id", ""),
                    "filename": metadata.get("filename", ""),
                    "page_number": page_number,
                    "embedding_model": metadata.get("embedding_model", ""),
                    "content": result["documents"][0][i] or "",
                    "score": 1.0 - distance,
                }
            )
        return hits

    def delete_by_kb(self, kb_id: str) -> None:
        try:
            self._collection.delete(where={"kb_id": kb_id})
        except Exception as e:
            LOGGER.error(f"[Chroma] 删除知识库向量失败: {e}")

    def delete_by_doc(self, doc_id: str) -> None:
        try:
            self._collection.delete(where={"doc_id": doc_id})
        except Exception as e:
            LOGGER.error(f"[Chroma] 删除文档向量失败: {e}")

    def delete_by_chunk(self, chunk_id: str) -> None:
        try:
            self._collection.delete(where={"chunk_id": chunk_id})
        except Exception as e:
            LOGGER.error(f"[Chroma] 删除分块向量失败: {e}")

    def delete_by_vector_id(self, vector_id: str) -> None:
        try:
            self._collection.delete(ids=[vector_id])
        except Exception as e:
            LOGGER.error(f"[Chroma] 删除向量失败: {e}")


chroma_store = ChromaStore()

# 向量重建入口（预留）：更换 Embedding 模型或迁移向量库时，可在此扩展 reindex 能力。
