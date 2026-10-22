# -*- coding: utf-8 -*-
from importlib import import_module


def __getattr__(name):
    modules = {
        "chain": {"is_irrelevant_question", "get_irrelevant_response", "format_context_from_results", "rag_query", "rag_stream"},
        "chroma_store": {"chroma_store"},
        "embeddings": {"is_embedding_configured", "get_embedding", "get_single_embedding"},
        "llm": {"OpenAICompatibleLLM", "format_messages"},
        "loader": {"load_pdf", "load_all_pdfs", "split_documents"},
    }
    for module, names in modules.items():
        if name in names:
            return getattr(import_module(f"{__name__}.{module}"), name)
    raise AttributeError(name)

__all__ = [
    "load_pdf", "load_all_pdfs", "split_documents",
    "is_irrelevant_question", "get_irrelevant_response", "format_context_from_results", "rag_query", "rag_stream",
    "chroma_store",
    "is_embedding_configured", "get_embedding", "get_single_embedding",
    "OpenAICompatibleLLM", "format_messages",
]
