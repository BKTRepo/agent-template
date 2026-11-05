from applications.knowledge_base.services.rag_document_crud import RagDocumentCrud as BaseCrud
from applications.wrq.knowledge_base.rag.scope import current_scope

class RagDocumentCrud(BaseCrud):
    async def list_all(self):
        allowed = current_scope.get()
        return [d for d in await super().list_all() if d.job_id in allowed]

    async def complete_doc_ids(self):
        return {d.job_id for d in await self.list_all() if d.status == 'complete'}
