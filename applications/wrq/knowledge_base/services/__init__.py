# -*- coding: utf-8 -*-
def __getattr__(name):
    # 新版 API 不应在导入时启动 Chroma 或要求旧 LangChain 分块器。
    if name in {"DocumentChunkCrud", "DocumentCrud", "KnowledgeBaseCrud"}:
        from . import knowledge_base_crud
        return getattr(knowledge_base_crud, name)
    raise AttributeError(name)

__all__ = ["KnowledgeBaseCrud", "DocumentCrud", "DocumentChunkCrud"]
