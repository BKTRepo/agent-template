# -*- coding: utf-8 -*-
"""分块公共工具模块 — 提供 token 估算与片段组装等共用函数"""

from typing import Any, Dict, List

_CHARS_PER_TOKEN = 1.3  # 中英文混合文本的经验系数


def estimate_tokens(text: str) -> int:
    """粗略估算中英文混合文本的 token 数"""
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def _assemble_chunks(
        fragments: List[str],
        chunk_chars: int,
        overlap_chars: int,
) -> List[Dict[str, Any]]:
    """将片段组装为指定大小的分块，并处理块间重叠"""
    if not fragments:
        return []

    chunks: List[Dict[str, Any]] = []
    current = ""
    order = 0

    for frag in fragments:
        tentative = current + ("\n\n" if current else "") + frag
        if len(tentative) <= chunk_chars:
            current = tentative
        else:
            if current.strip():
                chunks.append(_make_chunk(current.strip(), order))
                order += 1
                if overlap_chars > 0 and len(current) > overlap_chars:
                    current = current[-overlap_chars:]
                    if len(current + "\n\n" + frag) <= chunk_chars:
                        current = current + "\n\n" + frag
                        continue
                current = frag
            else:
                # 单个片段超限 — 按字符硬切
                for i in range(0, len(frag), max(1, chunk_chars)):
                    sub = frag[i:i + chunk_chars].strip()
                    if sub:
                        chunks.append(_make_chunk(sub, order))
                        order += 1
                current = ""

    if current.strip():
        chunks.append(_make_chunk(current.strip(), order))

    return chunks


def _make_chunk(content: str, order: int) -> Dict[str, Any]:
    """构造标准结构的分块字典"""
    return {
        "content": content,
        "tokens": estimate_tokens(content),
        "chunk_order_index": order,
    }
