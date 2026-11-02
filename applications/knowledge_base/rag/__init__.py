# -*- coding: utf-8 -*-
"""文档分块模块 — 仅递归字符切分（R 策略），实现移植自 LightRAG"""

from typing import Any, Dict, List

from applications.knowledge_base.rag.recursive_character import chunking_by_recursive_character
from applications.knowledge_base.rag.section_context import markdown_sections
from configure import PROJECT_CONFIG


def chunk_document(
        text: str,
        chunk_token_size: int = PROJECT_CONFIG.CHUNK_SIZE,
        chunk_overlap_token_size: int = PROJECT_CONFIG.CHUNK_OVERLAP,
        **kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    对文档执行递归字符分块

    :param text: 文档正文（Markdown 或纯文本）
    :param chunk_token_size: 目标分块 token 大小
    :param chunk_overlap_token_size: 相邻分块的重叠 token 大小
    :param kwargs: 透传给策略函数
    :return: {content, tokens, chunk_order_index} 字典列表
    """
    if not text or not text.strip():
        return []

    chunks = []
    # Do not carry overlap across heading boundaries: ownership must remain unambiguous.
    for section in markdown_sections(text):
        owned_chunks = chunking_by_recursive_character(
            text[section["start"]:section["end"]],
            chunk_token_size=chunk_token_size,
            chunk_overlap_token_size=chunk_overlap_token_size,
            **kwargs,
        )
        for chunk in owned_chunks:
            chunk.update({
                "section_path": section["section_path"],
                "section_title": section["section_title"],
                "section_field_no": section["section_field_no"],
                "section_status": "identified" if section["section_path"] else "unknown",
                "section_segments": [], "section_source": "markdown_heading",
                "section_context_version": 1,
            })
        chunks.extend(owned_chunks)
    for order, chunk in enumerate(chunks):
        chunk["chunk_order_index"] = order
    return chunks


__all__ = [
    "chunk_document",
    "chunking_by_recursive_character",
]
