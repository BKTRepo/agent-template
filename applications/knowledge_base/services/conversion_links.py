"""Attach /api/convert jobs to platform knowledge records without ingesting twice."""
import asyncio
import hashlib
from pathlib import Path
import shutil
import uuid

from tortoise.transactions import in_transaction

from applications.knowledge_base.models.knowledge_base_model import Document, DocumentChunk
from applications.knowledge_base.models.rag_document_model import RagDocument
from configure import PROJECT_CONFIG
from enums import DocumentStatus


async def stage_conversions(user, job_ids, kb_id):
    from .platform_service import KnowledgeError, KnowledgeService
    from .file_type import validate_file_type

    staged = []
    try:
        for job_id in dict.fromkeys(job_ids):
            job = await RagDocument.get_or_none(job_id=job_id, owner_id=user.id)
            if not job or job.status in {"deleting", "delete_failed"}:
                raise KnowledgeError("转换任务不存在或无权使用", "conversion_job_ids", 404)
            if job.knowledge_document_id:
                existing = await Document.get_or_none(id=job.knowledge_document_id, is_deleted=False)
                if not existing or existing.knowledge_base_id != kb_id:
                    raise KnowledgeError("转换任务已归属其他知识库", "conversion_job_ids", 409)
            source = Path(job.input_path or "").resolve()
            if not source.is_relative_to(Path(PROJECT_CONFIG.RAG_INPUT_DIR).resolve()) or not source.is_file():
                raise KnowledgeError("转换任务原文件不存在，请重新上传", "conversion_job_ids", 409)
            suffix = validate_file_type(job.filename)
            directory = PROJECT_CONFIG.upload_path / kb_id
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{uuid.uuid4().hex}.{suffix}"
            staged.append({"filename": job.filename, "file_type": suffix, "file_path": str(target),
                           "file_size": source.stat().st_size, "content_hash": job.file_sha256})
            await asyncio.to_thread(shutil.copyfile, source, target)
            def fingerprint():
                with target.open('rb') as stream:
                    return hashlib.file_digest(stream, 'sha256').hexdigest()
            actual_hash = await asyncio.to_thread(fingerprint)
            if job.file_sha256 and actual_hash != job.file_sha256:
                raise KnowledgeError("转换任务原文件校验失败，请重新上传", "conversion_job_ids", 409)
            staged[-1]['content_hash'] = actual_hash
        return staged
    except BaseException:
        KnowledgeService.clean_files(staged)
        raise


async def attach_conversions(user, job_ids, kb_id, connection):
    from .platform_service import KnowledgeError

    adopted = set()
    for job_id in dict.fromkeys(job_ids):
        job = await RagDocument.filter(job_id=job_id, owner_id=user.id).using_db(connection).select_for_update().first()
        if not job:
            raise KnowledgeError("转换任务归属已变化", "conversion_job_ids", 409)
        doc = await Document.filter(knowledge_base_id=kb_id, filename=job.filename, is_deleted=False).using_db(connection).first()
        if not doc:
            raise KnowledgeError("知识库文件与转换任务不一致", "conversion_job_ids", 409)
        if job.knowledge_document_id and job.knowledge_document_id != doc.id:
            raise KnowledgeError("转换任务已被其他文档使用", "conversion_job_ids", 409)
        await RagDocument.filter(knowledge_document_id=doc.id).exclude(job_id=job_id).using_db(connection).update(knowledge_document_id=None)
        job.knowledge_document_id = doc.id
        await job.save(using_db=connection, update_fields=["knowledge_document_id"])
        adopted.add(doc.id)
    return adopted


async def linked_conversion(document_id):
    return await RagDocument.filter(knowledge_document_id=document_id, job_id__startswith="doc-").first()


async def sync_conversion(job):
    """Only complete ingestion can populate completed platform documents/chunks."""
    from .rag_service import RagDocumentService

    job = await RagDocument.get_or_none(job_id=job.job_id)
    if not job or not job.knowledge_document_id:
        return
    doc = await Document.get_or_none(id=job.knowledge_document_id, is_deleted=False)
    if not doc or (doc.content_hash and doc.content_hash != job.file_sha256):
        return
    if job.status != "complete":
        failed = job.status in {"failed", "delete_failed"}
        await Document.filter(id=doc.id, generation=doc.generation, is_deleted=False).update(
            status=DocumentStatus.FAILED if failed else DocumentStatus.PROCESSING,
            error_message=job.summary if failed else None)
        return
    if doc.status == DocumentStatus.COMPLETED and doc.indexed_generation == doc.generation:
        return
    service = RagDocumentService()
    chunks = await service.get_document_chunks(job.job_id) or []
    markdown = await service.get_document_markdown(job.job_id) or ""
    if not chunks:
        await Document.filter(id=doc.id, generation=doc.generation).update(
            status=DocumentStatus.FAILED, error_message="入库任务已完成，但分块产物缺失，请检查处理服务")
        return
    new_ids = {f"{job.job_id}-chunk-{chunk['order']:04d}" for chunk in chunks}
    async with in_transaction() as connection:
        current = await Document.filter(id=doc.id, is_deleted=False).using_db(connection).select_for_update().first()
        active = await RagDocument.filter(job_id=job.job_id, knowledge_document_id=doc.id).using_db(connection).exists()
        if not active or not current or current.generation != doc.generation:
            return
        old_ids = [row.chroma_id for row in await DocumentChunk.filter(document_id=doc.id).using_db(connection)
                   if row.chroma_id and row.chroma_id not in new_ids]
        await DocumentChunk.filter(document_id=doc.id).using_db(connection).delete()
        await DocumentChunk.bulk_create([
            DocumentChunk(document_id=doc.id, content=chunk["content"], chunk_index=i,
                          chroma_id=f"{job.job_id}-chunk-{chunk['order']:04d}",
                          source_metadata={"job_id": job.job_id, "modality": chunk.get("modality")})
            for i, chunk in enumerate(chunks)], using_db=connection)
        current.markdown = markdown
        current.chunk_count = len(chunks)
        current.indexed_generation = current.generation
        current.embedding_model = PROJECT_CONFIG.EMBEDDING_MODEL
        current.cleanup_vector_ids = list(set(current.cleanup_vector_ids or []) | set(old_ids))
        await current.save(using_db=connection)
    if current.cleanup_vector_ids:
        from .document_pipeline import MilvusIndex
        await MilvusIndex().remove(current.cleanup_vector_ids)
    await Document.filter(id=doc.id, generation=doc.generation, is_deleted=False).update(
        status=DocumentStatus.COMPLETED, processing_started_time=None, error_message=None, cleanup_vector_ids=[])


async def sync_knowledge_conversions(kb_id):
    ids = await Document.filter(knowledge_base_id=kb_id, is_deleted=False).values_list("id", flat=True)
    jobs = await RagDocument.filter(knowledge_document_id__in=ids, job_id__startswith="doc-")
    for job in jobs:
        await sync_conversion(job)
    return {job.knowledge_document_id: job for job in jobs}
