# -*- coding: utf-8 -*-
"""递归字符分块模块（R 策略）— 多级分隔符级联切分，实现移植自 LightRAG

句子完整性设计要点：
1. 分隔符级联在词/字符级之前排入中英文句末标点（。！？；，及英文 ". "），
   超长段落优先在句子边界断开；
2. 切分时分隔符附着在前一片末尾（keep-separator），句末标点保留在分块内容中，
   相邻片段直接拼接即可忠实还原原文，不会把句子粘连成无标点长串；
3. 不设"阈值放弃"机制 — 始终采用文本中实际出现的最强分隔符，仅对仍超限的
   片段递归降级细分。旧实现的阈值检查会在长句较多时整体放弃句末标点级、
   落到逗号/词级切分，反而切断本可完整的句子；
4. 封口与块间重叠均落在完整片段（句子）边界上，下一块不会从句子中间开始。
"""

from typing import Any, Dict, List

from applications.wrq.knowledge_base.rag._common import _make_chunk, estimate_tokens
from configure import PROJECT_CONFIG

# 分隔符优先级 — 语义边界从强到弱。句末标点优先于词/字符级，
# 使切分点尽量落在句子边界。". "（句点+空格）是英文句子边界，
# 比单独的 "." 安全（不会切断数字/缩写）。
_RECURSIVE_SEPARATORS = [
    "\n\n",   # 段落边界
    "\n",     # 行边界
    "。",     # 中文句号
    "！",     # 中文叹号
    "？",     # 中文问号
    "；",     # 中文分号
    "，",     # 中文逗号
    ". ",     # 英文句子（句点+空格）
    " ",      # 词边界
    "",       # 字符级硬切（最后手段）
]


def chunking_by_recursive_character(
        text: str,
        chunk_token_size: int = PROJECT_CONFIG.CHUNK_SIZE,
        chunk_overlap_token_size: int = PROJECT_CONFIG.CHUNK_OVERLAP,
) -> List[Dict[str, Any]]:
    """递归字符切分器 — 按逐级变细的分隔符切分，尽量保持句子完整"""
    if not text or not text.strip():
        return []

    chunk_chars = int(chunk_token_size * 1.3)
    overlap_chars = int(chunk_overlap_token_size * 1.3)
    token_limit = estimate_tokens("x" * chunk_chars)
    fragments = _split_recursive(text, _RECURSIVE_SEPARATORS, chunk_chars, token_limit)
    return _assemble_recursive_chunks(fragments, chunk_chars, overlap_chars)


def _split_keeping_separator(text: str, sep: str) -> List[str]:
    """按 sep 切分，分隔符附着在前一片末尾 — 保留句末标点不丢失"""
    raw = text.split(sep)
    last = len(raw) - 1
    pieces: List[str] = []
    for i, part in enumerate(raw):
        piece = part + sep if i < last else part
        if piece:
            pieces.append(piece)
    return pieces


def _split_recursive(
        text: str,
        separators: List[str],
        chunk_chars: int,
        token_limit: int,
) -> List[str]:
    if not text.strip():
        return []

    for idx, sep in enumerate(separators):
        if sep == "":
            # 最后手段 — 字符级硬切
            return [
                text[i:i + chunk_chars]
                for i in range(0, max(1, len(text)), chunk_chars)
            ]

        if sep not in text:
            continue

        # 采用文本中实际出现的最强分隔符切分；仅对仍超限的片段
        # 递归降级到更细分隔符，其余片段原样保留（句子不被切断）
        result: List[str] = []
        for piece in _split_keeping_separator(text, sep):
            if not piece.strip():
                continue
            if estimate_tokens(piece) <= token_limit:
                result.append(piece)
            else:
                result.extend(
                    _split_recursive(piece, separators[idx + 1:], chunk_chars, token_limit)
                )
        return result

    # 文本中无任何分隔符 — 原样返回，由组装阶段兜底硬切
    return [text]


def _assemble_recursive_chunks(
        fragments: List[str],
        chunk_chars: int,
        overlap_chars: int,
) -> List[Dict[str, Any]]:
    """将片段组装为分块

    与通用 ``_assemble_chunks`` 的区别（均为句子完整性服务）：
    - 片段直接拼接（分隔符已附着在前一片末尾），不在相邻句子间伪造换行；
    - 封口必然落在片段边界；
    - 重叠从尾部按完整片段保留，避免下一块从句子中间开始。
    """
    chunks: List[Dict[str, Any]] = []
    current_parts: List[str] = []
    current_len = 0
    order = 0

    for frag in fragments:
        if not frag.strip():
            continue
        frag_len = len(frag)

        # 单个片段超限 — 先冲刷当前累积，再按字符硬切（兜底，
        # 对应不含任何分隔符的超长句，无法避免切断）
        if frag_len > chunk_chars:
            if current_parts:
                chunks.append(_make_chunk("".join(current_parts).strip(), order))
                order += 1
                current_parts, current_len = [], 0
            for i in range(0, frag_len, max(1, chunk_chars)):
                sub = frag[i:i + chunk_chars].strip()
                if sub:
                    chunks.append(_make_chunk(sub, order))
                    order += 1
            continue

        # 加入当前片段将超限 — 封口，并从尾部按完整片段保留重叠
        if current_parts and current_len + frag_len > chunk_chars:
            chunks.append(_make_chunk("".join(current_parts).strip(), order))
            order += 1
            overlap_parts: List[str] = []
            overlap_len = 0
            for part in reversed(current_parts):
                if overlap_len + len(part) > overlap_chars:
                    break
                overlap_parts.insert(0, part)
                overlap_len += len(part)
            # 重叠仅在能与本片段一起装进块上限时才保留: 否则 append 后
            # 当前块会超出 chunk_chars（超限块）, 且下一轮封口会把这份
            # 纯重叠内容冲刷成零新内容的重复块（与上一块尾部完全相同,
            # 检索时白白占用 top-k 槽位）。此时丢弃重叠、以本片段起新块
            # （与 _common._assemble_chunks 的同款防护保持一致）
            if overlap_len + frag_len > chunk_chars:
                overlap_parts, overlap_len = [], 0
            current_parts, current_len = overlap_parts, overlap_len

        current_parts.append(frag)
        current_len += frag_len

    if current_parts:
        body = "".join(current_parts).strip()
        if body:
            chunks.append(_make_chunk(body, order))

    return chunks
