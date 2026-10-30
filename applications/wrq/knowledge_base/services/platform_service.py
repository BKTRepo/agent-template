"""个人知识库：流式落盘、SQL 版本历史、文档级增量任务与权限校验。"""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import unicodedata
import uuid
import shutil

import anyio
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from applications.wrq.platform_catalog import validate_application
from applications.wrq.agent.models.agent_model import Skill
from applications.wrq.agent.services.skill_package_builder import safe_relative_path
from applications.wrq.knowledge_base.models.knowledge_base_model import KnowledgeBase, Document, DocumentChunk
from applications.wrq.knowledge_base.name_rules import name_key
from applications.wrq.knowledge_base.schemas.platform_schema import KnowledgeForm, next_version
from applications.wrq.knowledge_base.services.document_pipeline import DocumentPipeline
from applications.wrq.knowledge_base.services.document_lock import document_lock
from applications.wrq.knowledge_base.services.job_control import RetryableDeletionError, NonRetryableDeletionError
from applications.wrq.knowledge_base.services.file_type import validate_file_type
from applications.user.models.user_model import User
from configure import PROJECT_CONFIG, LOGGER
from enums import DocumentStatus


class KnowledgeError(Exception):
    def __init__(self, message, field="source", status_code=400):
        self.field, self.status_code = field, status_code
        super().__init__(message)


def _history(kb, user, summary, *, initial=False):
    if not initial:
        kb.revision += 1
    kb.history = list(kb.history or []) + [{"version": next_version(kb.revision), "maintainer_id": user.id,
        "maintainer": user.alias or user.username, "change_summary": summary,
        "created_at": datetime.now(timezone.utc).isoformat()}]


class KnowledgeService:
    def __init__(self, pipeline=None):
        self.pipeline = pipeline or DocumentPipeline()

    async def require(self, kb_id, user, *, write=False, connection=None):
        query = KnowledgeBase.filter(id=kb_id, state__not=1)
        if connection:
            query = query.using_db(connection).select_for_update()
        kb = await query.first()
        if not kb or (kb.user_id != user.id and not kb.is_public):
            raise KnowledgeError("知识库不存在或无访问权限", status_code=404)
        if write and kb.user_id != user.id:
            raise KnowledgeError("只有创建者可以修改知识库", status_code=403)
        return kb

    async def require_document(self, kb_id, doc_id, user, *, write=False):
        await self.require(kb_id, user, write=write)
        doc = await Document.filter(id=doc_id, knowledge_base_id=kb_id, is_deleted=False).first()
        if not doc:
            raise KnowledgeError("文档不存在", status_code=404)
        return doc

    async def check_name(self, value, exclude_id=None):
        key = name_key(value)
        # 兼容尚未回填规范化名称键的历史记录。
        for row in await KnowledgeBase.filter(state__not=1).exclude(id=exclude_id or "").all():
            if (row.name_key or name_key(row.knowledge_name)) == key:
                raise KnowledgeError("知识库名称已存在", "knowledge_name")

    async def stage(self, kb_id, files):
        saved = []
        directory = PROJECT_CONFIG.upload_path / kb_id
        directory.mkdir(parents=True, exist_ok=True)
        try:
            names = set()
            for index, upload in enumerate(files):
                filename = upload.filename or ""
                try:
                    safe_relative_path(filename)
                    if "/" in filename:
                        raise ValueError("文件名不能含目录")
                    file_type = validate_file_type(filename)
                except ValueError as exc:
                    raise KnowledgeError(str(exc), f"files[{index}]") from exc
                key = unicodedata.normalize("NFKC", filename).casefold()
                if key in names:
                    raise KnowledgeError("同一次上传不能包含同名文件", f"files[{index}]")
                names.add(key)
                path = directory / (uuid.uuid4().hex + "." + file_type)
                saved.append({"filename": filename, "file_type": file_type, "file_path": str(path)})
                digest, size = hashlib.sha256(), 0
                async with await anyio.open_file(path, "xb") as stream:
                    # 知识库定稿不设业务大小上限；分块写入，避免把整个文件读进内存。
                    while chunk := await upload.read(1024 * 1024):
                        digest.update(chunk); size += len(chunk)
                        await stream.write(chunk)
                if not size:
                    raise KnowledgeError("不能上传空文件", f"files[{index}]")
                saved[-1].update(content_hash=digest.hexdigest(), file_size=size)
            return saved
        except BaseException:
            self.clean_files(saved)
            raise

    @staticmethod
    def clean_files(saved, *, strict=False):
        root = PROJECT_CONFIG.upload_path.resolve()
        for item in saved:
            path = Path(item["file_path"]).resolve()
            if strict and (not path.is_relative_to(root) or path == root):
                raise ValueError("资源存储路径越界，不能确认删除完成")
            if path.is_relative_to(root):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    if strict:
                        raise
                    # Windows 正在下载的旧文件可能暂时被占用；不把已提交的保存误报为失败。
                    LOGGER.warning("知识库旧文件暂时无法清理，需在文件不再占用后维护清理：{}", path.name)

    async def save(self, user, form: KnowledgeForm, files, *, kb_id=None, expected_document=None):
        try:
            validate_application(form.application, allow_all=True)
        except ValueError as exc:
            raise KnowledgeError(str(exc), "application") from exc
        creating = kb_id is None
        if creating and not files:
            raise KnowledgeError("新建知识库至少上传一个文件", "files")
        if not creating:
            await self.require(kb_id, user, write=True)
            if not form.change_summary:
                raise KnowledgeError("编辑时请填写变更摘要", "change_summary")
        kb_id = kb_id or str(uuid.uuid4())
        staged = await self.stage(kb_id, files)
        jobs = []
        try:
            async with in_transaction() as conn:
                await self.check_name(form.knowledge_name, kb_id)
                if creating:
                    kb = KnowledgeBase(id=kb_id, user_id=user.id)
                else:
                    kb = await self.require(kb_id, user, write=True, connection=conn)
                    if form.expected_version and form.expected_version != next_version(kb.revision):
                        raise KnowledgeError("知识库已被修改，请刷新后重试", "expected_version", 409)
                kb.knowledge_name, kb.name_key = form.knowledge_name, name_key(form.knowledge_name)
                kb.description, kb.tag, kb.application = form.description, form.tag, form.application
                kb.is_public = form.is_public
                _history(kb, user, "创建知识库" if creating else form.change_summary, initial=creating)
                await kb.save(using_db=conn)
                docs = await Document.filter(knowledge_base_id=kb_id, is_deleted=False).using_db(conn).all()
                if expected_document:
                    doc_id, generation = expected_document
                    if not any(d.id == doc_id and d.generation == generation for d in docs):
                        raise KnowledgeError("文档已被修改，请刷新后重试", "expected_generation", 409)
                retained = set(form.retained_document_ids) if form.retained_document_ids is not None else {d.id for d in docs}
                if retained - {d.id for d in docs}:
                    raise KnowledgeError("保留文件列表包含无效文档", "retained_document_ids")
                by_name = {unicodedata.normalize("NFKC", d.filename).casefold(): d for d in docs}
                # 先检查最终文件集合，而不是让逐行更新的中间状态撞上哈希唯一索引。
                for item in staged:
                    previous = by_name.get(unicodedata.normalize("NFKC", item["filename"]).casefold())
                    if previous:
                        if previous.status == DocumentStatus.PROCESSING:
                            raise KnowledgeError("文档正在处理，请处理完成后再替换", "files", 409)
                        retained.add(previous.id)
                final_files = {unicodedata.normalize("NFKC", d.filename).casefold():
                    (d.filename, d.content_hash, None) for d in docs if d.id in retained}
                final_files.update({unicodedata.normalize("NFKC", item["filename"]).casefold():
                    (item["filename"], item["content_hash"], i) for i, item in enumerate(staged)})
                seen_hashes = {}
                for filename, digest, index in final_files.values():
                    if digest and digest in seen_hashes:
                        other, other_index = seen_hashes[digest]
                        field_index = index if index is not None else other_index
                        field = f"files[{field_index}]" if field_index is not None else "files"
                        raise KnowledgeError(f"附件「{filename}」与「{other}」内容重复，请保留一份", field)
                    if digest:
                        seen_hashes[digest] = (filename, index)
                if not final_files:
                    raise KnowledgeError("知识库至少保留一个文件", "files")
                changed_ids = [d.id for d in docs if d.id not in retained]
                for item in staged:
                    previous = by_name.get(unicodedata.normalize("NFKC", item["filename"]).casefold())
                    if previous and previous.content_hash != item["content_hash"]:
                        changed_ids.append(previous.id)
                if changed_ids:
                    # 事务内暂时释放变更/移除文档的旧哈希；失败会整体回滚。
                    await Document.filter(id__in=changed_ids).using_db(conn).update(content_hash=None)
                for item in staged:
                    previous = by_name.get(unicodedata.normalize("NFKC", item["filename"]).casefold())
                    if previous:
                        if previous.status == DocumentStatus.PROCESSING:
                            raise KnowledgeError("文档正在处理，请处理完成后再替换", "files", 409)
                        retained.add(previous.id)
                        if previous.content_hash == item["content_hash"] and previous.status == DocumentStatus.COMPLETED:
                            # 相同内容不重建向量，但用本次实际字节修复可能缺失/损坏的原文件。
                            previous.cleanup_file_paths = list(previous.cleanup_file_paths or []) + [previous.file_path]
                            for key, value in item.items():
                                setattr(previous, key, value)
                            await previous.save(using_db=conn)
                            jobs.append(previous.id)
                            continue
                        previous.cleanup_file_paths = list(previous.cleanup_file_paths or []) + [previous.file_path]
                        for key, value in item.items():
                            setattr(previous, key, value)
                        previous.generation += 1
                        previous.markdown = None
                        previous.status = DocumentStatus.PROCESSING
                        previous.error_message = None
                        previous.processing_started_time = None
                        previous.task_id = previous.task_dispatched_at = previous.next_retry_at = None
                        await previous.save(using_db=conn)
                        jobs.append(previous.id)
                    else:
                        doc = await Document.create(knowledge_base_id=kb_id, using_db=conn, **item)
                        retained.add(doc.id)
                        jobs.append(doc.id)
                for doc in docs:
                    if doc.id not in retained:
                        doc.is_deleted = True
                        doc.status = DocumentStatus.DELETING
                        doc.content_hash = None
                        # 使旧解析结果失效；清理任务等待同文档正在进行的外部写入收尾。
                        doc.generation += 1
                        doc.processing_started_time = None
                        doc.error_message = None
                        doc.task_id = doc.task_dispatched_at = doc.next_retry_at = None
                        doc.deletion_retry_count, doc.deletion_retryable, doc.deletion_error_type = 0, True, None
                        await doc.save(using_db=conn)
                        jobs.append(doc.id)
                if not await Document.filter(knowledge_base_id=kb_id, is_deleted=False).using_db(conn).exists():
                    raise KnowledgeError("知识库至少保留一个文件", "files")
        except IntegrityError as exc:
            self.clean_files(staged)
            raise KnowledgeError("知识库名称或文档内容重复，请检查后重试", "knowledge_name") from exc
        except BaseException:
            self.clean_files(staged)
            raise
        # 旧路径已持久写入文档；后续任务严格清理，失败后不会只剩一条日志。
        return await self.detail(kb_id, user), jobs

    async def detail(self, kb_id, user):
        kb = await self.require(kb_id, user)
        docs = await Document.filter(knowledge_base_id=kb_id).order_by("created_time")
        visible_docs = [d for d in docs if not d.is_deleted]
        status = "processing" if any(d.status in {DocumentStatus.PROCESSING, DocumentStatus.DELETING}
            and (not d.is_deleted or d.deletion_retryable) for d in docs) else (
            "failed" if any(d.status in {DocumentStatus.FAILED, DocumentStatus.DELETE_FAILED}
                or (d.is_deleted and not d.deletion_retryable) for d in docs) else "completed")
        creator = await User.get(id=kb.user_id)
        from applications.wrq.agent.models.agent_model import SkillResourceBinding
        current = await Skill.filter(state=0).values_list('current_version_id', flat=True)
        count = await SkillResourceBinding.filter(skill_version_id__in=current,
            source_type='knowledge_base',source_id=kb_id).count()
        return {"id": kb.id, "knowledge_name": kb.knowledge_name, "description": kb.description,
            "tag": kb.tag, "application": kb.application, "version": next_version(kb.revision),
            "user_id": kb.user_id, "maintainer": creator.alias or creator.username,
            "is_public": kb.is_public, "can_edit": kb.user_id == user.id,
            "status": status, "document_count": len(visible_docs), "reference_count": count,
            "created_time": kb.created_time.isoformat(), "updated_time": kb.updated_time.isoformat(),
            "history": kb.history or [], "documents": [self.document_out(d) for d in visible_docs],
            "cleanup_pending": [d.id for d in docs if d.is_deleted],
            "cleanup_tasks": [{"document_id": d.id, "filename": d.filename,
                "status": "delete_failed" if d.status in {DocumentStatus.FAILED, DocumentStatus.DELETE_FAILED} or not d.deletion_retryable else "deleting",
                "error_message": d.error_message,
                "can_retry": d.status in {DocumentStatus.FAILED, DocumentStatus.DELETE_FAILED} or not d.deletion_retryable,
                "retry_count": d.deletion_retry_count, "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
                "error_type": d.deletion_error_type}
                for d in docs if d.is_deleted]}

    @staticmethod
    def document_out(doc):
        return {"id": doc.id, "knowledge_base_id": doc.knowledge_base_id, "filename": doc.filename,
            "file_type": doc.file_type, "file_size": doc.file_size, "content_hash": doc.content_hash,
            "generation": doc.generation, "indexed_generation": doc.indexed_generation,
            "status": doc.status.value if isinstance(doc.status, DocumentStatus) else doc.status,
            "chunk_count": doc.chunk_count, "error_message": doc.error_message,
            "has_markdown": bool(doc.markdown), "updated_time": doc.updated_time.isoformat()}

    async def list(self, user, search="", *, offset=0, limit=50):
        qs = KnowledgeBase.filter(Q(user_id=user.id) | Q(is_public=True), state__not=1)
        if search.strip():
            qs = qs.filter(knowledge_name__icontains=search.strip())
        total = await qs.count()
        rows = await qs.order_by("-updated_time").offset(offset).limit(limit)
        return [await self.detail(row.id, user) for row in rows], total

    async def process(self, doc_id):
        async with document_lock(doc_id):
            doc = await Document.get_or_none(id=doc_id)
            if not doc:
                return
            if doc.is_deleted:
                await self._delete_document(doc)
            else:
                await self.pipeline._process(doc_id)
                await self.clean_retired_files(doc_id)

    async def clean_retired_files(self, doc_id):
        doc = await Document.get_or_none(id=doc_id)
        if not doc or not doc.cleanup_file_paths:
            return
        self.clean_files([{"file_path": p} for p in doc.cleanup_file_paths], strict=True)
        await Document.filter(id=doc_id, generation=doc.generation).update(cleanup_file_paths=[])

    async def _delete_document(self, doc, *, propagate=False, lease=None):
        # 删除意图和向量 ID 保留到全部外部清理成功；重复回调或失败重试均安全。
        if doc.status not in {DocumentStatus.PROCESSING, DocumentStatus.DELETING}:
            return
        doc_id, generation = doc.id, doc.generation
        stage = "索引"
        try:
            if lease:
                await lease.renew()
            ids = [c.chroma_id for c in await DocumentChunk.filter(document_id=doc_id) if c.chroma_id]
            if hasattr(self.pipeline.index, "remove_document"):
                await self.pipeline.index.remove_document(doc_id)
            await self.pipeline.index.remove(list(dict.fromkeys(ids + list(doc.cleanup_vector_ids or []))))
            stage = "原文件"
            if lease:
                await lease.renew()
            await anyio.to_thread.run_sync(lambda: self.clean_files(
                [{"file_path": p} for p in [doc.file_path] + list(doc.cleanup_file_paths or [])], strict=True))
            stage = "解析产物"
            root = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR).resolve()
            for value in doc.artifact_paths or []:
                path = Path(value).resolve()
                if path == root or not path.is_relative_to(root):
                    raise ValueError("解析产物路径越界")
                if path.exists():
                    await anyio.to_thread.run_sync(lambda: shutil.rmtree(path))
            if lease:
                await lease.renew()
            await Document.filter(id=doc_id, generation=generation, is_deleted=True).delete()
        except Exception as exc:
            LOGGER.exception("知识库文档删除失败: {} ({})", doc_id, stage)
            await Document.filter(id=doc_id, generation=generation, is_deleted=True).update(
                status=DocumentStatus.DELETING if propagate else DocumentStatus.DELETE_FAILED,
                deletion_retryable=propagate and not isinstance(exc, ValueError),
                deletion_error_type=type(exc).__name__, processing_started_time=None,
                error_message=f"移除文档{stage}失败，记录已保留，请重试清理")
            if propagate:
                cls = NonRetryableDeletionError if isinstance(exc, ValueError) else RetryableDeletionError
                raise cls(f"移除文档{stage}失败") from exc

    async def retry(self, kb_id, user, doc_id=None):
        await self.require(kb_id, user, write=True)
        query = Document.filter(knowledge_base_id=kb_id)
        if doc_id:
            query = query.filter(id=doc_id)
        jobs = []
        # 支持显式恢复崩溃后残留任务；不在读接口或进程启动时偷偷重置状态。
        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        async with in_transaction() as conn:
            await self.require(kb_id, user, write=True, connection=conn)
            docs = await query.using_db(conn).select_for_update().all()
            if doc_id and not docs:
                raise KnowledgeError("文档不存在", "documents", 404)
            for doc in docs:
                retryable = doc.status in {DocumentStatus.FAILED, DocumentStatus.DELETE_FAILED} or (doc.status in {DocumentStatus.PROCESSING, DocumentStatus.DELETING} and (
                    not doc.processing_started_time or doc.processing_started_time < stale))
                if not retryable:
                    continue
                doc.status = DocumentStatus.DELETING if doc.is_deleted else DocumentStatus.PROCESSING
                doc.error_message = doc.processing_started_time = None
                doc.task_id = doc.task_dispatched_at = doc.next_retry_at = None
                doc.deletion_retry_count, doc.deletion_retryable, doc.deletion_error_type = 0, True, None
                doc.generation += 1  # 使崩溃恢复前仍存活的旧工作结果失效。
                await doc.save(using_db=conn)
                jobs.append(doc.id)
        if not jobs:
            raise KnowledgeError("没有失败或可恢复的文档任务", "documents", 409)
        return jobs

    async def edit_text(self, kb_id, doc_id, user, data):
        import io
        from fastapi import UploadFile
        kb = await self.require(kb_id, user, write=True)
        doc = await self.require_document(kb_id, doc_id, user, write=True)
        if doc.file_type not in {"md", "txt"}:
            raise KnowledgeError("Word、Excel 和 PDF 请通过上传同名新文件修改；文本编辑仅用于 Markdown/TXT", "content")
        form = KnowledgeForm(knowledge_name=kb.knowledge_name, description=kb.description, tag=kb.tag,
            application=kb.application, is_public=kb.is_public, change_summary=data.change_summary,
            expected_version=next_version(kb.revision))
        upload = UploadFile(filename=doc.filename, file=io.BytesIO(data.content.encode("utf-8")))
        try:
            return await self.save(user, form, [upload], kb_id=kb_id,
                                   expected_document=(doc_id, data.expected_generation))
        finally:
            await upload.close()


async def get_knowledge_service():
    return KnowledgeService()
