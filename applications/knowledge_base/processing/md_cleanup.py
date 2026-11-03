# -*- coding: utf-8 -*-
"""Markdown 清理工具——目录（TOC）、图片引用与页眉页脚等无用内容移除。

在解析完成后、术语提取与分块嵌入之前调用（见 rag_pipeline._run_post_parse_pipeline）,
纯正则实现, 不依赖 LLM。依次清除:

1. 图片引用: ``![Image](artifacts/picture-0000.png)`` 之类的 Markdown 图片语法
   （图片信息走多模态分析通道, 文本管道中属于噪声）;
2. 目录标题区段: ``# 目录`` / ``# Contents`` 等标题之后, 直到同级或更高级
   标题之前的全部内容;
3. 表格式目录块: 单列表格 + 点线引导符 + 行尾页码的连续行块, 形如::

       | Subfield 04 (Sender Street Address)............. 960 |
       |------------------------------------------------------|
       | Subfield 05 (Sender City).......................961  |

   多列数据表（单元格内含竖线）不会被误识别;
4. 文本式目录行（兜底）: ``1. Introduction ........ 3`` 之类的散行;
5. 页眉/页脚: PDF 每页重复的装饰行（版权行、页码行、文档题头）, 三条判定路径:
   a. 高频重复短行: 数字归一化后重复 ≥ _HF_REPEAT_THRESHOLD 次的短行
      （页码 ``Page 3 of 120`` 归一为同一键, 跨页累计命中）;
   b. 装饰关键词行: 含 ©/copyright/版权所有/机密 等关键词且重复 ≥ 2 次;
   c. 显式页码行: ``第 3 页 共 120 页`` / ``Page 3 of 120`` 等强特征 ≥ 2 次,
      ``- 3 -`` / ``3 / 120`` 等弱特征（无"页/page"字样）≥ 3 次——纯数字
      行永不删除（可能是数据内容）。
   标题（#）、表格行（|）、引用、列表项、图片与注释行永不参与判定。
   局限: 清洗面向独立成行的页眉页脚; 与正文粘连在同一行的页码无法分离。
"""

import re
from typing import Dict, List

from configure import LOGGER

# ==================== 图片引用 ====================

# Markdown 图片语法: ![alt](uri)
_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\([^)]*\)")

# ==================== 目录: 标题区段 ====================

# 标记目录区段起始的标题（# ~ ### 级）
_TOC_HEADINGS = re.compile(
    r"^(#{1,3})\s*(目录|目\s*录|Table\s*of\s*Contents|Contents|Index)",
    re.IGNORECASE,
)

# ==================== 目录: 表格式 ====================

# 单格表格行: 首尾各一个竖线, 单元格内无其他竖线（表头/条目/分隔行通吃）
_SINGLE_CELL_ROW = re.compile(r"^\|[^|]*\|$")
# 点线引导符: 连续 ASCII 点号（≥6）或中文省略号（≥2）
_DOT_LEADER = re.compile(r"\.{6,}|…{2,}")
# 行尾页码: 数字后可带空白, 以 | 收尾
_TRAILING_PAGE_NO = re.compile(r"\d+\s*\|$")

# 目录块判定阈值: 连续单格表格区域至少含 N 条点线条目才整体删除,
# 避免误删正文中偶发的单列表格
_TOC_BLOCK_MIN_ENTRIES = 3

# ==================== 目录: 文本式（兜底） ====================

# 非表格的目录条目行（章节名 ... 页码）
_TOC_TEXT_LINE_PATTERNS = [
    # 中英文点线目录: "1. Introduction ............. 3"
    re.compile(r"\.{4,}\s*\d+\s*$"),
    # 长空白后以页码结尾: "Chapter 1          5"
    # （\S 锚定空白串起点, 避免 ".{2,}" 与 "\s{10,}" 匹配同一段空白造成二次回溯,
    #   宽表填充行可达上千字符, 旧写法在大文档上有灾难性回溯风险）
    re.compile(r"\S\s{10,}\d+\s*$"),
    # 中文省略号点线: "概述……………… 1"
    re.compile(r"…{2,}\s*\d+\s*$"),
]

# ==================== 页眉 / 页脚 ====================

# 候选行长度上限: 页眉页脚是短行, 长行一律视为正文。60 字符足以覆盖
# 版权行/页码行/文档题头, 同时放过正文中逐字重复的样板长句
# （如 "The ... currently does not use this data element." 78 字符）
_HF_MAX_LINE_CHARS = 60

# 通用路径: 归一化后重复次数阈值。取 8 是保守权衡——10 页以上的文档
# 页眉页脚重复次数必然 ≥ 10, 而正文中逐字重复 8 次的独立短行极少;
# 页数更少的文档靠关键词/显式页码路径兜底
_HF_REPEAT_THRESHOLD = 8

# 装饰关键词路径: 强语义特征, 重复 ≥ 2 次即删
_HF_KEYWORD_MIN_REPEATS = 2

# 显式页码行: 强特征（含"页/page"字样）与弱特征（纯结构）分档,
# 弱特征阈值更高, 防止误删 "2024/2025" 之类正文年份行
_HF_PAGE_NO_MIN_STRONG = 2
_HF_PAGE_NO_MIN_WEAK = 3

# 永不参与页眉页脚判定的行首形式: 标题 / 表格行 / 引用 / 图片 / 注释 / 列表项
_HF_EXCLUDED_HEAD = ("#", "|", ">", "![", "<!--")
_HF_BULLET_LINE = re.compile(r"^[-*+•]\s")
_HF_NUMBERED_LINE = re.compile(r"^\d+[.)、．]\s")

# 装饰关键词: 版权 / 保密类页脚特征词
_HF_DECOR_KEYWORDS = re.compile(
    r"©|copyright|all rights reserved|proprietary|confidential"
    r"|版权所有|著作权|保密|机密|内部资料|内部使用",
    re.IGNORECASE,
)

# 显式页码行（强特征: 含"页/page"字样, 正文撞型概率极低）
_HF_PAGE_NO_STRONG = re.compile(
    r"^("
    r"(第\s*)?\d+\s*页(\s*[,，/／]?\s*(共\s*)?\d+\s*页)?"  # 第 3 页 / 3 页, 共 120 页
    r"|page\s*\d+(\s*(of|/|／)\s*\d+)?"                    # Page 3 (of 120)
    r")$",
    re.IGNORECASE,
)

# 显式页码行（弱特征: 无"页/page"字样的结构式页码, 阈值更严）
_HF_PAGE_NO_WEAK = re.compile(
    r"^("
    r"[-–—]\s*\d+\s*[-–—]"  # - 3 -
    r"|\d+\s*[/／]\s*\d+"   # 3 / 120
    r")$",
)


def _remove_images(markdown: str) -> str:
    """删除 Markdown 图片引用; 整行仅由图片构成时连行删除, 原有空行保留。"""
    lines: List[str] = []
    for line in markdown.split("\n"):
        cleaned = _IMAGE_PATTERN.sub("", line).rstrip()
        if cleaned.strip():
            lines.append(cleaned)
        elif not line.strip():
            lines.append(line)
        # 其余情况（整行仅图片/图片+空白）→ 丢弃该行
    return "\n".join(lines)


def _remove_toc_heading_sections(lines: List[str]) -> List[str]:
    """删除「# 目录 / # Contents」标题区段（至同级或更高级标题之前）。"""
    result: List[str] = []
    in_toc = False
    toc_heading_level = 0
    skip_blank = False

    for line in lines:
        stripped = line.strip()

        # ── 检测目录区段的开始 ──
        m = _TOC_HEADINGS.match(stripped)
        if m:
            in_toc = True
            toc_heading_level = len(m.group(1))  # # 字符的数量
            skip_blank = True  # 跳过标题行本身
            continue

        # ── 目录区段内：检查是否遇到同级 / 更高级标题 ──
        if in_toc:
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                if level <= toc_heading_level:
                    in_toc = False
                    # 该标题不属于目录——予以保留
                    result.append(line)
                    continue
            # 跳过紧跟目录标题之后的空行
            if skip_blank and not stripped:
                continue
            skip_blank = False
            # 跳过目录区段内的全部内容
            continue

        result.append(line)

    return result


def _is_toc_entry_row(stripped: str) -> bool:
    """表格式目录条目行: 单格表格行 + 点线引导符 + 行尾页码。"""
    return bool(
        _SINGLE_CELL_ROW.match(stripped)
        and _DOT_LEADER.search(stripped)
        and _TRAILING_PAGE_NO.search(stripped)
    )


def _remove_toc_blocks(lines: List[str]) -> List[str]:
    """删除表格式目录块。

    扫描连续的单格表格行区域（允许夹杂 |----| 分隔行、单格表头行与空行）,
    区域内点线条目数 ≥ ``_TOC_BLOCK_MIN_ENTRIES`` 时整块删除。多列数据表的
    行内含多个竖线, 不匹配单格模式, 天然不会被误删。
    """
    result: List[str] = []
    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].strip()
        if _SINGLE_CELL_ROW.match(stripped):
            # 向后收集连续的单格表格区域
            j, entry_count = i, 0
            while j < n:
                s = lines[j].strip()
                if not s:
                    j += 1  # 块内空行一并纳入考察
                elif _SINGLE_CELL_ROW.match(s):
                    if _is_toc_entry_row(s):
                        entry_count += 1
                    j += 1
                else:
                    break
            if entry_count >= _TOC_BLOCK_MIN_ENTRIES:
                i = j  # 整块删除（含块内空行）
                continue
        result.append(lines[i])
        i += 1
    return result


def _is_toc_text_line(stripped: str) -> bool:
    """文本式目录行（非表格）: 点线/长空白 + 行尾页码。"""
    if not stripped or stripped.startswith("#"):
        return False
    return any(p.search(stripped) for p in _TOC_TEXT_LINE_PATTERNS)


def _is_hf_candidate(stripped: str) -> bool:
    """页眉页脚候选行: 短行且非标题/表格行/引用/图片/注释/列表项。

    列表项排除很关键: 如 "- EBCDIC (Code Page 1047)" 含 "Page 1047" 但
    是正文条目; 表格行排除保护重复的表头行（如 "| Attribute | Description |"
    可重复上百次）。
    """
    if not stripped or len(stripped) > _HF_MAX_LINE_CHARS:
        return False
    if stripped.startswith(_HF_EXCLUDED_HEAD):
        return False
    if _HF_BULLET_LINE.match(stripped) or _HF_NUMBERED_LINE.match(stripped):
        return False
    return True


def _normalize_hf_line(stripped: str) -> str:
    """页眉页脚归一化键: 小写 + 空白折叠 + 数字串替换为 N。

    使 "Page 3 of 120" 与 "Page 4 of 120"、"© 1997–2024 …" 与
    "© 1997–2025 …" 归入同一键跨页累计, 页码逐页变化的页脚也能命中。
    """
    s = re.sub(r"\s+", " ", stripped.lower())
    return re.sub(r"\d+", "N", s)


def _remove_headers_footers(lines: List[str]) -> List[str]:
    """删除页眉/页脚行 — 三条判定路径, 全部要求"跨页重复"证据。

    1. 高频重复短行: 归一化键重复 ≥ _HF_REPEAT_THRESHOLD;
    2. 装饰关键词行: 含版权/保密特征词且重复 ≥ _HF_KEYWORD_MIN_REPEATS;
    3. 显式页码行: 强特征 ≥ _HF_PAGE_NO_MIN_STRONG, 弱特征
       ≥ _HF_PAGE_NO_MIN_WEAK。

    单页文档与不重复的内容不会被误删; 被删行的判定依据是全文重复次数,
    因此本步骤幂等（清洗后残留行重复次数必然低于阈值）。
    """
    counts: Dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if _is_hf_candidate(stripped):
            key = _normalize_hf_line(stripped)
            counts[key] = counts.get(key, 0) + 1

    result: List[str] = []
    removed = 0
    for line in lines:
        stripped = line.strip()
        if _is_hf_candidate(stripped):
            cnt = counts.get(_normalize_hf_line(stripped), 0)
            if (
                cnt >= _HF_REPEAT_THRESHOLD
                or (cnt >= _HF_KEYWORD_MIN_REPEATS and _HF_DECOR_KEYWORDS.search(stripped))
                or (cnt >= _HF_PAGE_NO_MIN_STRONG and _HF_PAGE_NO_STRONG.match(stripped))
                or (cnt >= _HF_PAGE_NO_MIN_WEAK and _HF_PAGE_NO_WEAK.match(stripped))
            ):
                removed += 1
                continue
        result.append(line)

    if removed:
        LOGGER.debug(f"页眉页脚清洗: 移除 {removed} 行重复装饰行")
    return result


def clean_markdown(markdown: str) -> str:
    """清洗 Markdown: 图片引用 → 目录标题区段 → 表格式目录块 → 文本式目录行
    → 页眉页脚。

    幂等: 对已清洗过的文本再次调用结果不变（重试等场景可能重复执行清洗）。
    """
    if not markdown:
        return markdown

    markdown = _remove_images(markdown)
    lines = _remove_toc_heading_sections(markdown.split("\n"))
    lines = _remove_toc_blocks(lines)
    lines = [line for line in lines if not _is_toc_text_line(line.strip())]
    lines = _remove_headers_footers(lines)
    return "\n".join(lines)
