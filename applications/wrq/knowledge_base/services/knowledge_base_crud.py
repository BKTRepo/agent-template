# -*- coding: utf-8 -*-
import hashlib
import os
import uuid
from typing import List, Optional, Tuple

from fastapi import UploadFile
from langchain_text_splitters import RecursiveCharacterTextSplitter
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q

from applications.base.rag.chroma_store import chroma_store
from applications.base.rag.embeddings import get_embedding
from applications.base.services.scaffold import ScaffoldCrud
from applications.wrq.knowledge_base.models.knowledge_base_model import (
    Document,
    DocumentChunk,
    KnowledgeBase,
)
from applications.wrq.knowledge_base.schemas.knowledge_base_schema import (
    DocumentChunkCreate,
    DocumentChunkOut,
    DocumentChunkUpdate,
    DocumentCreate,
    DocumentOut,
    DocumentUpdate,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
)
from applications.wrq.knowledge_base.services.document_loader import load_document_pages
from applications.wrq.knowledge_base.services.file_type import validate_file_type
from applications.user.models.user_model import User
from configure import PROJECT_CONFIG
from core.exceptions import (
    DataBaseStorageException,
    NoPermissionException,
    NotFoundException,
    ParameterException,
)
from enums import DocumentStatus


class DocumentCrud(ScaffoldCrud[Document, DocumentCreate, DocumentUpdate]):
    def __init__(self):
        super().__init__(model=Document)

    async def get_by_knowledge_base(
            self, knowledge_base_id: str, document_id: str
    ) -> Optional[Document]:
        """根据知识库 ID 和文档 ID 获取文档"""
        return await self.model.get_or_none(
            id=document_id, knowledge_base_id=knowledge_base_id
        )

    async def get_by_content_hash(
            self, knowledge_base_id: str, content_hash: str
    ) -> Optional[Document]:
        """根据知识库 ID 和内容哈希获取文档"""
        return await self.model.get_or_none(
            knowledge_base_id=knowledge_base_id, content_hash=content_hash
        )

    async def list_by_knowledge_base(self, knowledge_base_id: str) -> List[Document]:
        """获取知识库下的文档列表"""
        return await self.model.filter(
            knowledge_base_id=knowledge_base_id
        ).order_by("-created_time")

    async def count_by_knowledge_base(self, knowledge_base_id: str) -> int:
        """统计知识库下的文档数量"""
        return await self.model.filter(knowledge_base_id=knowledge_base_id).count()

    async def create_for_knowledge_base(
            self, knowledge_base_id: str, **kwargs
    ) -> Document:
        """在指定知识库下创建文档"""
        return await self.model.create(knowledge_base_id=knowledge_base_id, **kwargs)


class DocumentChunkCrud(ScaffoldCrud[DocumentChunk, DocumentChunkCreate, DocumentChunkUpdate]):
    def __init__(self):
        super().__init__(model=DocumentChunk)

    async def bulk_create_chunks(self, chunks: List[DocumentChunk]) -> None:
        """批量创建文档分块"""
        await self.model.bulk_create(chunks)

    async def list_by_knowledge_base(
            self,
            knowledge_base_id: str,
            document_id: str = None,
            page: int = 1,
            page_size: int = 50,
    ) -> List[DocumentChunk]:
        """获取知识库下的文档分块列表"""
        qs = self.model.filter(document__knowledge_base_id=knowledge_base_id)
        if document_id:
            qs = qs.filter(document_id=document_id)
        offset = (page - 1) * page_size
        return await qs.order_by("chunk_index").offset(offset).limit(page_size)

    async def get_by_knowledge_base(
            self, knowledge_base_id: str, chunk_id: str
    ) -> Optional[DocumentChunk]:
        """根据知识库 ID 和分块 ID 获取文档分块"""
        return (
            await self.model.filter(
                id=chunk_id, document__knowledge_base_id=knowledge_base_id
            )
            .prefetch_related("document")
            .first()
        )

    async def count_by_document(self, document_id: str) -> int:
        """统计文档下的分块数量"""
        return await self.model.filter(document_id=document_id).count()


class KnowledgeBaseCrud(ScaffoldCrud[KnowledgeBase, KnowledgeBaseCreate, KnowledgeBaseCreate]):
    def __init__(self):
        super().__init__(model=KnowledgeBase)
        self.document = DocumentCrud()
        self.chunk = DocumentChunkCrud()

    @staticmethod
    def _content_hash(content: bytes) -> str:
        """计算文件内容 SHA256"""
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _can_replace_on_reupload(status: DocumentStatus) -> bool:
        """失败或处理中卡住时，允许同内容重传覆盖"""
        return status in (DocumentStatus.FAILED, DocumentStatus.PROCESSING)

    @staticmethod
    def _resolve_chunk_config(kb: KnowledgeBase) -> Tuple[int, int]:
        """解析知识库分块参数，未配置时回退全局默认值"""
        chunk_size = kb.chunk_size or PROJECT_CONFIG.CHUNK_SIZE
        chunk_overlap = kb.chunk_overlap if kb.chunk_overlap is not None else PROJECT_CONFIG.CHUNK_OVERLAP
        if chunk_overlap > chunk_size // 2:
            chunk_overlap = chunk_size // 2
        return chunk_size, chunk_overlap

    async def get_by_id(self, kb_id: str) -> Optional[KnowledgeBase]:
        """根据 ID 获取知识库（排除已禁用）"""
        return await self.model.filter(id=kb_id, state__not=1).first()

    async def list_for_user(
            self, user_id: int, search: str = None
    ) -> List[KnowledgeBase]:
        """获取用户可见的知识库列表"""
        qs = self.model.filter(
            Q(user_id=user_id) | Q(is_public=True),
            state__not=1,
        )
        if search:
            qs = qs.filter(
                Q(knowledge_name__icontains=search) | Q(description__icontains=search)
            )
        return await qs.order_by("-updated_time")

    def check_access(self, kb: KnowledgeBase, user: User) -> None:
        """校验知识库访问权限"""
        if not kb.is_public and kb.user_id != user.id:
            raise NoPermissionException(message="没有权限访问该知识库")

    def check_write(self, kb: KnowledgeBase, user: User) -> None:
        """校验知识库写权限"""
        if kb.user_id != user.id:
            raise NoPermissionException(message="没有权限操作该知识库")

    @staticmethod
    def _to_document_out(doc: Document) -> DocumentOut:
        return DocumentOut(
            id=doc.id,
            knowledge_base_id=doc.knowledge_base_id,
            filename=doc.filename,
            file_type=doc.file_type,
            file_size=doc.file_size,
            content_hash=doc.content_hash,
            embedding_model=doc.embedding_model,
            chunk_count=doc.chunk_count,
            status=doc.status.value if isinstance(doc.status, DocumentStatus) else doc.status,
            error_message=doc.error_message,
            created_time=doc.created_time,
            updated_time=doc.updated_time,
        )

    @staticmethod
    def _to_chunk_out(chunk: DocumentChunk) -> DocumentChunkOut:
        return DocumentChunkOut(
            id=chunk.id,
            document_id=chunk.document_id,
            content=chunk.content,
            chunk_index=chunk.chunk_index,
            page_number=chunk.page_number,
            created_time=chunk.created_time,
            updated_time=chunk.updated_time,
        )

    async def _to_out(self, kb: KnowledgeBase) -> KnowledgeBaseOut:
        doc_count = await self.document.count_by_knowledge_base(kb.id)
        return KnowledgeBaseOut(
            id=kb.id,
            knowledge_name=kb.knowledge_name,
            description=kb.description,
            user_id=kb.user_id,
            is_public=kb.is_public,
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap,
            default_embedding_model=PROJECT_CONFIG.EMBEDDING_MODEL_NAME,
            created_time=kb.created_time,
            updated_time=kb.updated_time,
            document_count=doc_count,
        )

    async def create_kb(self, user: User, data: KnowledgeBaseCreate) -> KnowledgeBaseOut:
        """创建知识库"""
        kb = await self.model.create(
            user_id=user.id,
            knowledge_name=data.knowledge_name,
            description=data.description,
            is_public=data.is_public,
            chunk_size=data.chunk_size,
            chunk_overlap=data.chunk_overlap,
        )
        return await self._to_out(kb)

    async def list_kbs(self, user: User, search: str = None) -> List[KnowledgeBaseOut]:
        """获取当前用户可见的知识库列表"""
        kbs = await self.list_for_user(user.id, search)
        return [await self._to_out(kb) for kb in kbs]

    async def get_kb(self, kb_id: str, user: User) -> KnowledgeBaseOut:
        """获取知识库详情"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_access(kb, user)
        return await self._to_out(kb)

    async def update_kb(
            self, kb_id: str, user: User, data: KnowledgeBaseCreate
    ) -> KnowledgeBaseOut:
        """更新知识库"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_write(kb, user)
        kb.knowledge_name = data.knowledge_name
        kb.description = data.description
        kb.is_public = data.is_public
        kb.chunk_size = data.chunk_size
        kb.chunk_overlap = data.chunk_overlap
        await kb.save()
        return await self._to_out(kb)

    async def delete_kb(self, kb_id: str, user: User) -> None:
        """软删除知识库（state=1），并清理向量索引"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_write(kb, user)
        chroma_store.delete_by_kb(kb_id)
        kb.state = 1
        await kb.save()

    async def _purge_document(self, doc: Document) -> None:
        """物理删除文档及其分块、向量与本地文件"""
        chroma_store.delete_by_doc(doc.id)
        await DocumentChunk.filter(document_id=doc.id).delete()
        if os.path.exists(doc.file_path):
            os.remove(doc.file_path)
        await doc.delete()

    async def _process_document(self, kb: KnowledgeBase, doc: Document) -> None:
        """解析文档、分块并写入向量库"""
        chroma_store.delete_by_doc(doc.id)
        await DocumentChunk.filter(document_id=doc.id).delete()

        doc.status = DocumentStatus.PROCESSING
        doc.error_message = None
        doc.chunk_count = 0
        doc.embedding_model = PROJECT_CONFIG.EMBEDDING_MODEL_NAME
        await doc.save()

        try:
            chunk_size, chunk_overlap = self._resolve_chunk_config(kb)
            pages = load_document_pages(doc.file_path, doc.file_type)
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=["\n\n", "\n", "。", "；", "，", " ", ""],
            )

            chunk_models: List[DocumentChunk] = []
            chunk_index = 0
            for page in pages:
                raw_page = page.metadata.get("page")
                page_number = int(raw_page) + 1 if raw_page is not None else None
                for chunk_text in splitter.split_text(page.page_content):
                    if not chunk_text or not chunk_text.strip():
                        continue
                    chunk_models.append(
                        DocumentChunk(
                            id=str(uuid.uuid4()),
                            document_id=doc.id,
                            content=chunk_text,
                            chunk_index=chunk_index,
                            page_number=page_number,
                        )
                    )
                    chunk_index += 1

            if not chunk_models:
                raise DataBaseStorageException(message="文档解析后无有效文本分块，请检查 PDF 内容")

            await self.chunk.bulk_create_chunks(chunk_models)

            embeddings = get_embedding([c.content for c in chunk_models])
            chroma_chunks = [
                {
                    "doc_id": doc.id,
                    "chunk_id": chunk.id,
                    "content": chunk.content,
                    "embedding": emb,
                    "page_number": chunk.page_number,
                    "filename": doc.filename,
                    "embedding_model": doc.embedding_model,
                }
                for chunk, emb in zip(chunk_models, embeddings)
            ]
            chroma_ids = chroma_store.upsert_chunks(kb.id, chroma_chunks)

            for chunk, chroma_id in zip(chunk_models, chroma_ids):
                chunk.chroma_id = chroma_id
            await DocumentChunk.bulk_update(chunk_models, fields=["chroma_id"])

            doc.status = DocumentStatus.COMPLETED
            doc.chunk_count = len(chunk_models)
            await doc.save()
        except Exception as e:
            chroma_store.delete_by_doc(doc.id)
            await DocumentChunk.filter(document_id=doc.id).delete()
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            doc.chunk_count = 0
            await doc.save()
            raise DataBaseStorageException(message=f"文档处理失败: {str(e)}")

    async def upload_document(
            self, kb_id: str, user: User, file: UploadFile
    ) -> DocumentOut:
        """上传并处理文档"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_write(kb, user)

        try:
            file_type = validate_file_type(file.filename)
        except ValueError as e:
            raise ParameterException(message=str(e))

        content = await file.read()
        content_hash = self._content_hash(content)

        existing_doc = await self.document.get_by_content_hash(kb_id, content_hash)
        if existing_doc:
            if self._can_replace_on_reupload(existing_doc.status):
                await self._purge_document(existing_doc)
            else:
                raise ParameterException(
                    message=(
                        f"该文档内容已存在于当前知识库"
                        f"（与「{existing_doc.filename}」相同），请勿重复上传"
                    )
                )

        kb_upload_dir = PROJECT_CONFIG.upload_path / kb_id
        kb_upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = kb_upload_dir / file.filename
        with open(file_path, "wb") as f:
            f.write(content)

        try:
            doc = await self.document.create_for_knowledge_base(
                kb_id,
                filename=file.filename,
                file_type=file_type,
                file_path=str(file_path),
                file_size=len(content),
                content_hash=content_hash,
                embedding_model=PROJECT_CONFIG.EMBEDDING_MODEL_NAME,
                status=DocumentStatus.PROCESSING,
            )
        except IntegrityError:
            raise ParameterException(message="该文档内容已存在于当前知识库，请勿重复上传")

        await self._process_document(kb, doc)
        return self._to_document_out(doc)

    async def retry_document(
            self, kb_id: str, doc_id: str, user: User
    ) -> DocumentOut:
        """重试处理失败的文档（使用已上传的本地文件）"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_write(kb, user)

        doc = await self.document.get_by_knowledge_base(kb_id, doc_id)
        if not doc:
            raise NotFoundException(message="文档不存在")
        if doc.status != DocumentStatus.FAILED:
            raise ParameterException(message="仅失败状态的文档支持重试")
        if not os.path.exists(doc.file_path):
            raise ParameterException(message="原始文件不存在，请重新上传")

        await self._process_document(kb, doc)
        return self._to_document_out(doc)

    async def reindex_kb_vectors(self, kb_id: str, user_id: int) -> dict:
        """全量重建知识库向量：清空 Chroma 索引后重新处理所有可用文档。"""
        from applications.user.models.user_model import User

        user = await User.get_or_none(id=user_id)
        if not user:
            raise NotFoundException(message="用户不存在")
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_write(kb, user)

        chroma_store.delete_by_kb(kb_id)
        docs = await self.document.list_by_knowledge_base(kb_id)
        result = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "errors": []}

        for doc in docs:
            if doc.status == DocumentStatus.PROCESSING:
                result["skipped"] += 1
                continue
            if not os.path.exists(doc.file_path):
                result["failed"] += 1
                result["errors"].append({
                    "doc_id": doc.id,
                    "filename": doc.filename,
                    "error": "原始文件不存在",
                })
                continue
            result["total"] += 1
            try:
                await self._process_document(kb, doc)
                result["success"] += 1
            except Exception as e:
                result["failed"] += 1
                result["errors"].append({
                    "doc_id": doc.id,
                    "filename": doc.filename,
                    "error": str(e),
                })
        return result

    async def retry_failed_documents(self, kb_id: str, user_id: int) -> dict:
        """批量重试知识库下状态为失败的文档。"""
        from applications.user.models.user_model import User

        user = await User.get_or_none(id=user_id)
        if not user:
            raise NotFoundException(message="用户不存在")
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_write(kb, user)

        docs = await Document.filter(
            knowledge_base_id=kb_id,
            status=DocumentStatus.FAILED,
        ).all()
        result = {"total": len(docs), "success": 0, "failed": 0, "errors": []}

        for doc in docs:
            if not os.path.exists(doc.file_path):
                result["failed"] += 1
                result["errors"].append({
                    "doc_id": doc.id,
                    "filename": doc.filename,
                    "error": "原始文件不存在",
                })
                continue
            try:
                await self._process_document(kb, doc)
                result["success"] += 1
            except Exception as e:
                result["failed"] += 1
                result["errors"].append({
                    "doc_id": doc.id,
                    "filename": doc.filename,
                    "error": str(e),
                })
        return result

    async def list_documents(self, kb_id: str, user: User) -> List[DocumentOut]:
        """获取知识库下的文档列表"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_access(kb, user)
        docs = await self.document.list_by_knowledge_base(kb_id)
        return [self._to_document_out(doc) for doc in docs]

    async def delete_document(self, kb_id: str, doc_id: str, user: User) -> None:
        """删除文档"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_write(kb, user)
        doc = await self.document.get_by_knowledge_base(kb_id, doc_id)
        if not doc:
            raise NotFoundException(message="文档不存在")
        chroma_store.delete_by_doc(doc_id)
        if os.path.exists(doc.file_path):
            os.remove(doc.file_path)
        await doc.delete()

    async def list_chunks(
            self,
            kb_id: str,
            user: User,
            document_id: str = None,
            page: int = 1,
            page_size: int = 50,
    ) -> List[DocumentChunkOut]:
        """获取知识库下的文档分块列表"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_access(kb, user)
        chunks = await self.chunk.list_by_knowledge_base(
            kb_id, document_id, page, page_size
        )
        return [self._to_chunk_out(chunk) for chunk in chunks]

    async def get_chunk(self, kb_id: str, chunk_id: str, user: User) -> DocumentChunkOut:
        """获取文档分块详情"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_access(kb, user)
        chunk = await self.chunk.get_by_knowledge_base(kb_id, chunk_id)
        if not chunk:
            raise NotFoundException(message="知识块不存在")
        return self._to_chunk_out(chunk)

    async def update_chunk(
            self, kb_id: str, chunk_id: str, user: User, data: DocumentChunkUpdate
    ) -> DocumentChunkOut:
        """更新文档分块"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_write(kb, user)
        chunk = await self.chunk.get_by_knowledge_base(kb_id, chunk_id)
        if not chunk:
            raise NotFoundException(message="知识块不存在")

        chunk.content = data.content
        embedding = get_embedding([data.content])[0]
        if chunk.chroma_id:
            chroma_store.delete_by_vector_id(chunk.chroma_id)
        filename = chunk.document.filename if chunk.document else None
        embedding_model = chunk.document.embedding_model if chunk.document else None
        chroma_ids = chroma_store.upsert_chunks(
            kb_id,
            [
                {
                    "doc_id": chunk.document_id,
                    "chunk_id": chunk.id,
                    "content": chunk.content,
                    "embedding": embedding,
                    "page_number": chunk.page_number,
                    "filename": filename,
                    "embedding_model": embedding_model,
                }
            ],
        )
        chunk.chroma_id = chroma_ids[0]
        await chunk.save()
        return self._to_chunk_out(chunk)

    async def delete_chunk(self, kb_id: str, chunk_id: str, user: User) -> None:
        """删除文档分块"""
        kb = await self.get_by_id(kb_id)
        if not kb:
            raise NotFoundException(message="知识库不存在")
        self.check_write(kb, user)
        chunk = await self.chunk.get_by_knowledge_base(kb_id, chunk_id)
        if not chunk:
            raise NotFoundException(message="知识块不存在")
        if chunk.chroma_id:
            chroma_store.delete_by_vector_id(chunk.chroma_id)
        document_id = chunk.document_id
        await chunk.delete()
        doc = await self.document.get_by_knowledge_base(kb_id, document_id)
        if doc:
            doc.chunk_count = await self.chunk.count_by_document(document_id)
            await doc.save()
