"""平台知识库适配 dev-knowledge: MarkItDown → 术语 → 摘要 → 分块 → Milvus。"""
import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from tortoise.transactions import in_transaction
from applications.knowledge_base.models.knowledge_base_model import Document, DocumentChunk, KnowledgeBase
from applications.knowledge_base.models.rag_document_model import RagDocument
from applications.knowledge_base.services.document_lock import document_lock
from applications.knowledge_base.services.job_control import DocumentCancelled
from applications.knowledge_base.services.rag_pipeline import RagPipelineService
from applications.knowledge_base.services.rag_service import RagDocumentService
from configure import LOGGER, PROJECT_CONFIG
from enums import DocumentStatus


class MilvusIndex:
    async def remove(self, ids):
        if not ids:
            return
        from applications.knowledge_base.rag.milvus_store import _milvus_client, _ensure_collection, _COLLECTION_NAME
        def remove():
            with _milvus_client() as client:
                _ensure_collection(client)
                client.delete(collection_name=_COLLECTION_NAME, ids=ids)
        await asyncio.to_thread(remove)

    async def remove_document(self, document_id):
        from applications.knowledge_base.rag.milvus_store import delete_by_doc_id
        for job in await RagDocument.filter(knowledge_document_id=document_id):
            await asyncio.to_thread(delete_by_doc_id, job.job_id)
        await asyncio.to_thread(delete_by_doc_id, document_id)
        await RagDocument.filter(knowledge_document_id=document_id).delete()


class DocumentPipeline:
    def __init__(self, index=None):
        self.index = index or MilvusIndex()

    async def process(self, document_id):
        async with document_lock(document_id):
            await self._process(document_id)

    async def _process(self, document_id, *, control=None):
        from .conversion_links import linked_conversion, sync_conversion
        conversion = await linked_conversion(document_id)
        if conversion:
            await sync_conversion(conversion)
            return
        async with in_transaction() as conn:
            doc = await Document.filter(id=document_id).using_db(conn).select_for_update().first()
            if not doc or doc.is_deleted or doc.status != DocumentStatus.PROCESSING or doc.processing_started_time:
                return
            generation = doc.generation
            await Document.filter(id=doc.id).using_db(conn).update(processing_started_time=datetime.now(timezone.utc))
        job_id = 'kb-' + hashlib.sha256(f'{doc.id}:{generation}'.encode()).hexdigest()[:32]
        try:
            path = Path(doc.file_path).resolve()
            if not path.is_relative_to(PROJECT_CONFIG.upload_path.resolve()) or not path.is_file():
                raise ValueError('原文件不存在或存储路径无效，请重新上传')
            if control:
                await control.check()
            service = RagDocumentService()
            entry = await service.get_document_entry(job_id)
            if not entry:
                # Namespaced internal filenames allow equal filenames in different knowledge bases.
                filename = job_id + path.suffix.lower()
                entry = service.make_doc_entry(job_id, filename, str(path))
                kb = await KnowledgeBase.get(id=doc.knowledge_base_id)
                entry.update(owner_id=kb.user_id, knowledge_document_id=doc.id,
                             file_sha256=doc.content_hash, do_ocr=False, force_ocr=False, enable_vlm=False)
                entry = await service.create_document(entry)
            elif entry['status'] == 'failed' or entry.get('cancel_requested'):
                entry.update(status='parsing', cancel_requested=False, resume=service._resume_artifacts_ready(entry))
                entry = await service.save_document(entry, bypass_guard=True)
            output = str((Path(PROJECT_CONFIG.RAG_OUTPUT_DIR) / job_id).resolve())
            await Document.filter(id=doc.id, generation=generation, is_deleted=False).update(
                artifact_paths=list(dict.fromkeys(list(doc.artifact_paths or []) + [output])))
            if entry['status'] == 'complete':
                # Recover a completed ingestion after the platform SQL write or cleanup was interrupted.
                result = {'success': True}
            else:
                pipeline = RagPipelineService(service)
                task = asyncio.create_task(pipeline.process_document(job_id, execution_token=doc.task_id))
                try:
                    while not task.done():
                        await asyncio.wait({task}, timeout=PROJECT_CONFIG.KNOWLEDGE_CANCEL_POLL_SECONDS)
                        if control:
                            await control.check()
                    result = await task
                except BaseException:
                    await service.update_document(job_id, {'cancel_requested':True})
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise
            markdown = await service.get_document_markdown(job_id) or ''
            await Document.filter(id=doc.id, generation=generation, is_deleted=False).update(markdown=markdown)
            if not result.get('success'):
                raise RuntimeError(result.get('error') or '知识处理未完成')
            chunks = await service.get_document_chunks(job_id) or []
            if not chunks:
                raise ValueError('入库结果缺少分块')
            if control:
                await control.check()
            async with in_transaction() as conn:
                current = await Document.filter(id=doc.id).using_db(conn).select_for_update().first()
                if not current or current.is_deleted or current.generation != generation:
                    raise DocumentCancelled('文档已更新，旧处理结果不再生效')
                new_ids = {f"{job_id}-chunk-{chunk['order']:04d}" for chunk in chunks}
                old_ids = [row.chroma_id for row in await DocumentChunk.filter(document_id=doc.id).using_db(conn) if row.chroma_id and row.chroma_id not in new_ids]
                await DocumentChunk.filter(document_id=doc.id).using_db(conn).delete()
                await DocumentChunk.bulk_create([DocumentChunk(document_id=doc.id,content=chunk['content'],
                    chunk_index=i,chroma_id=f"{job_id}-chunk-{chunk['order']:04d}",source_metadata={'job_id':job_id,'modality':chunk.get('modality')})
                    for i,chunk in enumerate(chunks)], using_db=conn)
                current.cleanup_vector_ids = old_ids
                current.chunk_count, current.indexed_generation = len(chunks), generation
                current.embedding_model = PROJECT_CONFIG.EMBEDDING_MODEL
                await current.save(using_db=conn)
            await self.index.remove(old_ids)
            await Document.filter(id=doc.id,generation=generation,is_deleted=False).update(
                status=DocumentStatus.COMPLETED,processing_started_time=None,error_message=None,cleanup_vector_ids=[])
        except Exception as exc:
            if isinstance(exc, DocumentCancelled) or (control and control.stop.is_set()):
                return
            LOGGER.exception('知识库迁移流水线失败: {}',doc.id)
            await Document.filter(id=doc.id,generation=generation,is_deleted=False).update(
                status=DocumentStatus.FAILED,processing_started_time=None,
                error_message=f'知识处理失败（{type(exc).__name__}），请检查处理日志后重试')
