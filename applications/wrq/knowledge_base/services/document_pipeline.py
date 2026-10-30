"""复用 RAG 章节分块及现有 embedding/Chroma；新索引成功前保留旧分块。"""
import asyncio
import math
from numbers import Real
from datetime import datetime, timezone
from pathlib import Path
import uuid

from tortoise.transactions import in_transaction

from applications.wrq.knowledge_base.models.knowledge_base_model import Document, DocumentChunk, KnowledgeBase
from applications.wrq.knowledge_base.rag import chunk_document
from applications.wrq.knowledge_base.services.document_loader import load_document_pages
from applications.wrq.knowledge_base.services.document_lock import document_lock
from applications.wrq.knowledge_base.services.job_control import DocumentCancelled
from configure import PROJECT_CONFIG, LOGGER
from enums import DocumentStatus


class ChromaIndex:
    """延迟初始化外部依赖；没有模型配置时如实报失败。"""
    async def embed(self, texts):
        from applications.base.rag.embeddings import get_embedding
        return await asyncio.to_thread(get_embedding, texts)

    async def put(self, kb_id, rows):
        from applications.base.rag.chroma_store import chroma_store
        return await asyncio.to_thread(chroma_store.upsert_chunks, kb_id, rows)

    async def remove(self, ids):
        if ids:
            from applications.base.rag.chroma_store import chroma_store
            # 不能使用旧封装吞掉异常，否则清理失败会被误报为成功。
            await asyncio.to_thread(chroma_store._collection.delete, ids=ids)
            remaining = await asyncio.to_thread(chroma_store._collection.get, ids=ids, include=[])
            if remaining["ids"]:
                raise RuntimeError("向量删除后仍有残留，请重试清理")

    async def remove_document(self, document_id):
        from applications.base.rag.chroma_store import chroma_store
        # 按文档过滤，覆盖旧流程遗漏的向量，而不仅仅依赖 SQL 里已记录的 ID。
        where = {"doc_id": document_id}
        await asyncio.to_thread(chroma_store._collection.delete, where=where)
        remaining = await asyncio.to_thread(chroma_store._collection.get, where=where, limit=1, include=[])
        if remaining["ids"]:
            raise RuntimeError("文档向量仍有残留")


async def parse_document(path, file_type, *, control=None, bundle_name=None):
    if file_type == "pdf" and PROJECT_CONFIG.KNOWLEDGE_PDF_DOCLING:
        from common.docling_native import convert_pdf_to_bundle
        raw = await asyncio.to_thread(Path(path).read_bytes)
        bundle = await convert_pdf_to_bundle(raw, Path(path).name, bundle_name or uuid.uuid4().hex,
            do_ocr=True, force_ocr=False, should_cancel=control.stop.is_set if control else None)
        return bundle.markdown
    if control:
        from .cancellable_parser import parse_in_process
        return await parse_in_process(path, file_type, control.stop)
    pages = await asyncio.to_thread(load_document_pages, path, file_type)
    return "\n\n".join(page.page_content for page in pages)


class DocumentPipeline:
    def __init__(self, index=None):
        self.index = index or ChromaIndex()

    @staticmethod
    async def remember_vectors(document_id, ids, *, generation=None):
        async with in_transaction() as conn:
            current = await Document.filter(id=document_id).using_db(conn).select_for_update().first()
            if not current or (generation is not None and (current.generation != generation or current.is_deleted)):
                raise ValueError("文档已更新，本次向量写入已取消")
            current.cleanup_vector_ids = list(dict.fromkeys(list(current.cleanup_vector_ids or []) + ids))
            await current.save(using_db=conn, update_fields=["cleanup_vector_ids"])

    async def process(self, document_id):
        async with document_lock(document_id):
            await self._process(document_id)

    async def _process(self, document_id, *, control=None):
        # 数据库领取任务；重复回调不重复向量化，进程崩溃后允许显式恢复。
        async with in_transaction() as conn:
            doc = await Document.filter(id=document_id).using_db(conn).select_for_update().first()
            if not doc or doc.is_deleted or doc.status != DocumentStatus.PROCESSING or doc.processing_started_time:
                return
            doc.processing_started_time = datetime.now(timezone.utc)
            await doc.save(using_db=conn, update_fields=["processing_started_time"])
            generation = doc.generation
        new_ids = []
        try:
            root = PROJECT_CONFIG.upload_path.resolve()
            path = Path(doc.file_path).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("原文件不存在或存储路径无效，请重新上传")
            if control:
                await control.check()
            bundle_name = f"knowledge-{doc.id}-{generation}"
            if doc.file_type == "pdf" and PROJECT_CONFIG.KNOWLEDGE_PDF_DOCLING:
                async with in_transaction() as conn:
                    current = await Document.filter(id=doc.id).using_db(conn).select_for_update().first()
                    current.artifact_paths = list(dict.fromkeys(list(current.artifact_paths or []) +
                        [str(Path(PROJECT_CONFIG.RAG_OUTPUT_DIR) / bundle_name)]))
                    await current.save(using_db=conn, update_fields=["artifact_paths"])
            markdown = await parse_document(str(path), doc.file_type, control=control, bundle_name=bundle_name)
            if control:
                await control.check()
            if not markdown.strip():
                raise ValueError("文档未解析出文本；扫描 PDF 请启用 Docling OCR 后重试")
            kb = await KnowledgeBase.get(id=doc.knowledge_base_id)
            chunks = await asyncio.to_thread(chunk_document, markdown,
                chunk_token_size=kb.chunk_size or PROJECT_CONFIG.CHUNK_SIZE,
                chunk_overlap_token_size=kb.chunk_overlap if kb.chunk_overlap is not None else PROJECT_CONFIG.CHUNK_OVERLAP)
            if not chunks:
                raise ValueError("文档没有有效文本分块")
            if not await Document.filter(id=doc.id, generation=generation, is_deleted=False).exists():
                return
            # 即使向量服务不可用，也保留真实解析结果，便于查看失败原因。
            await Document.filter(id=doc.id, generation=generation, is_deleted=False).update(markdown=markdown)
            embeddings = await self.index.embed([chunk["content"] for chunk in chunks])
            if control:
                await control.check()
            if (not isinstance(embeddings, (list, tuple)) or len(embeddings) != len(chunks)
                    or any(not isinstance(vector, (list, tuple)) or not vector for vector in embeddings)
                    or len({len(vector) for vector in embeddings}) != 1
                    or any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)
                           for vector in embeddings for value in vector)):
                raise ValueError("向量服务返回数量或内容不正确")
            new_ids = [str(uuid.uuid4()) for _ in chunks]
            models = [DocumentChunk(id=vector_id, document_id=doc.id, content=chunk["content"],
                chunk_index=i, chroma_id=vector_id, source_metadata={k: v for k, v in chunk.items() if k != "content"})
                for i, (vector_id, chunk) in enumerate(zip(new_ids, chunks))]
            # 先记录写入意图；即使进程在 put 与 SQL 切换之间崩溃，重试也能清理孤立向量。
            await self.remember_vectors(doc.id, new_ids, generation=generation)
            await self.index.put(kb.id, [{"vector_id": mid, "chunk_id": mid, "doc_id": doc.id,
                "content": chunk["content"], "embedding": embedding, "filename": doc.filename,
                "embedding_model": PROJECT_CONFIG.EMBEDDING_MODEL_NAME}
                for mid, chunk, embedding in zip(new_ids, chunks, embeddings)])
            if control:
                await control.check()
            async with in_transaction() as conn:
                current = await Document.filter(id=doc.id).using_db(conn).select_for_update().first()
                if not current or current.is_deleted or current.generation != generation:
                    raise ValueError("文档已更新，本次处理结果已失效")
                old = await DocumentChunk.filter(document_id=doc.id).using_db(conn).all()
                cleanup = [value for value in dict.fromkeys(list(current.cleanup_vector_ids or []) +
                    [c.chroma_id for c in old if c.chroma_id]) if value not in new_ids]
                await DocumentChunk.filter(document_id=doc.id).using_db(conn).delete()
                await DocumentChunk.bulk_create(models, using_db=conn)
                current.cleanup_vector_ids = cleanup
                current.chunk_count = len(models)
                current.indexed_generation = generation
                current.embedding_model = PROJECT_CONFIG.EMBEDDING_MODEL_NAME
                await current.save(using_db=conn)
            # 先更新 SQL 指针再清理旧索引，保持原 RAG 增量更新的失败保护原则。
            new_ids = []
            await self.index.remove(cleanup)
            await Document.filter(id=doc.id, generation=generation, is_deleted=False).update(status=DocumentStatus.COMPLETED,
                error_message=None, processing_started_time=None, cleanup_vector_ids=[])
        except Exception as exc:
            if new_ids:
                try:
                    await self.index.remove(new_ids)
                except Exception:
                    LOGGER.exception("清理失败的知识库新向量出错")
                    await self.remember_vectors(doc.id, new_ids)
            LOGGER.exception("知识库文档处理失败: {}", doc.id)
            if isinstance(exc, DocumentCancelled) or (control and control.stop.is_set()):
                return  # 删除／新代次 owns 状态，旧任务不能覆写为 failed。
            await Document.filter(id=doc.id, generation=generation, is_deleted=False).update(status=DocumentStatus.FAILED,
                error_message=f"文档处理失败（{type(exc).__name__}），请检查解析依赖、模型配置及服务器日志后重试",
                processing_started_time=None)
