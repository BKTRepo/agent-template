# -*- coding: utf-8 -*-
"""表格行级分块——从 sidecar 的 tables.json 生成表级摘要块与行级块。

不依赖 VLM: 行的自然语言描述由规则模板渲染（表头与单元格值配对）;
元数据（表名、行号）编织进分块 content, 与行数据一起参与向量化。
生成的块与文本块并存入库（方案一, 由 PROJECT_CONFIG.TABLE_ROW_CHUNKS 控制）。
"""

import json
import math
import re
from statistics import median
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from configure import LOGGER, PROJECT_CONFIG

# ==================== HTML 表格解析 ====================


def parse_html_table(html: str) -> List[List[str]]:
    """简易 HTML 表格解析器: <tr>/<th|td> → 二维字符串列表。"""
    rows: List[List[str]] = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL):
        cells = re.findall(r"<t[hd]>(.*?)</t[hd]>", tr, re.DOTALL)
        rows.append([c.strip() for c in cells])
    return rows


# ==================== 目录表识别（与 md_cleanup 口径一致） ====================

_DOT_LEADER = re.compile(r"\.{6,}|…{2,}")
_TRAILING_PAGE_NO = re.compile(r"\d\s*$")


def _trim_trailing_empty(row: List[str]) -> List[str]:
    """剔除行尾部的空字符串列。"""
    while row and row[-1] == "":
        row = row[:-1]
    return row


def is_toc_table(rows: List[List[str]]) -> bool:
    """单列且多数行呈「点线引导符 + 行尾页码」形态 → 判定为目录表。

    供 sidecar 生成端（不写入 tables.json）与各消费端（行级分块、
    VLM 分析兜底）共用, 保证全链路口径一致。

    兼容 docling 的两类常见偏差:
    1. 尾部空列: 表渲染为两列但第二列恒空, 实质仍是单列目录;
    2. 单元格内容重复: 长文本被 docling 拆入第二列但与第一列相同。
    对这两种情况, 仅取每行第一列进行目录特征判定。
    """
    if not rows:
        return False
    # 取每行第一列（忽略 docling 产生的尾部空列/重复列）
    first_col = [(r[0] if r else "") for r in rows]
    body = first_col[1:] if len(first_col) > 1 else first_col
    hits = sum(
        1 for cell in body
        if cell and _DOT_LEADER.search(cell) and _TRAILING_PAGE_NO.search(cell.strip())
    )
    return len(body) > 0 and hits / len(body) >= 0.6


# ==================== 分块构建 ====================


def _table_name(entry: Dict[str, Any], ordinal: int, stem: str) -> str:
    """表名: 取首个非空题注, 缺省回退「{文件名主干} 表 {序号}」。"""
    for caption in entry.get("captions") or []:
        if isinstance(caption, str) and caption.strip():
            return caption.strip()
    return f"{stem or '文档'} 表 {ordinal}"


def _header_labels(header: List[str], width: int) -> List[str]:
    """表头标签: 空表头回退为「第 N 列」。"""
    labels = []
    for j in range(width):
        h = header[j].strip() if j < len(header) else ""
        labels.append(h or f"第 {j + 1} 列")
    return labels


# ==================== Markdown 表格提取 ====================

# GFM pipe-table 行: 以 | 开头、以 | 结尾（允许尾随空白）
_PIPE_ROW = re.compile(r"^\|.+\|\s*$")
_TABLE_TITLE = re.compile(r"^\s*Table\s+\d+\b", re.IGNORECASE)
_CODE_TABLE_TITLE = re.compile(
    r"\b(?:code|codes|valid\s+values?|identifier|reason|result|category|"
    r"indicator|transaction\s+type|tag|value)\b",
    re.IGNORECASE,
)
_FIELD_NUMBER = re.compile(r"\b(?:Field|DE)\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_CODE_CELL = re.compile(r"^(?:\d{1,4}(?:\.\d+)?|[A-Z]{1,3}\d{0,3})$", re.IGNORECASE)


def _first_provenance(item: Dict[str, Any]) -> Tuple[Optional[int], Dict[str, Any]]:
    """返回 Docling 文本节点的页号和 bbox；缺失时使用空值。"""
    prov = item.get("prov") or []
    first = prov[0] if prov and isinstance(prov[0], dict) else {}
    page_no = first.get("page_no")
    bbox = first.get("bbox") if isinstance(first.get("bbox"), dict) else {}
    return page_no if isinstance(page_no, int) else None, bbox


def _nearest_section_heading(texts: List[Dict[str, Any]], index: int) -> str:
    """查找表题之前最近的非表格章节标题，作为表格行的父级语境。"""
    for item in reversed(texts[max(0, index - 160):index]):
        if item.get("label") != "section_header":
            continue
        value = str(item.get("text") or "").strip()
        if value and not _TABLE_TITLE.match(value):
            return value
    return ""


_COLUMN_X_TOLERANCE = 8.0  # PDF 点；容忍同列字形/缩进产生的小幅偏移


def _recover_code_table_columns(
    header_cells: List[Dict[str, Any]],
    row_groups: List[List[Dict[str, Any]]],
) -> Optional[List[Tuple[float, str]]]:
    """恢复多行表头的列起点；只有可验证的列名才参与值的配对。

    Docling 可能把相邻表头合成一个节点。仅当 bbox 内的各词起点能与
    已知列起点逐一对齐时拆开；无法确认时返回 None，不按非空值顺序猜列。
    """
    if not header_cells or not row_groups:
        return None
    anchors: List[float] = []
    for cell in sorted(header_cells, key=lambda item: item["left"]):
        if not anchors or cell["left"] - anchors[-1] > _COLUMN_X_TOLERANCE:
            anchors.append(cell["left"])
    code_left = median(row[0]["left"] for row in row_groups)
    if not anchors or abs(anchors[0] - code_left) > _COLUMN_X_TOLERANCE:
        return None

    # 仅从至少两行都出现、且处于合并表头 bbox 内的起点补充列。
    # 普通描述列内的缩进不应被误认成新列。
    repeated: List[Tuple[float, set]] = []
    for row_index, row in enumerate(row_groups):
        for cell in row:
            group = next((entry for entry in repeated
                          if abs(entry[0] - cell["left"]) <= _COLUMN_X_TOLERANCE), None)
            if group is None:
                repeated.append((cell["left"], {row_index}))
            else:
                group[1].add(row_index)
    for left, rows in repeated:
        if len(rows) < 2 or any(abs(left - anchor) <= _COLUMN_X_TOLERANCE
                                for anchor in anchors):
            continue
        for header in header_cells:
            right = header.get("right")
            if right is None or not (header["left"] + _COLUMN_X_TOLERANCE < left < right):
                continue
            words = list(re.finditer(r"\S+", header["text"]))
            if any(abs(header["left"] + (right - header["left"])
                       * word.start() / len(header["text"]) - left)
                   <= _COLUMN_X_TOLERANCE for word in words[1:]):
                anchors.append(left)
                break
    anchors.sort()
    if len(anchors) < 2:
        return None

    parts: List[List[str]] = [[] for _ in anchors]
    for cell in header_cells:
        column = min(range(len(anchors)), key=lambda i: abs(anchors[i] - cell["left"]))
        right = cell.get("right")
        spanned = [i for i, anchor in enumerate(anchors)
                   if i >= column and right is not None
                   and cell["left"] - _COLUMN_X_TOLERANCE <= anchor < right]
        if len(spanned) <= 1:
            parts[column].append(cell["text"])
            continue
        # 宽表头可能是横跨多列的总标题，也可能是粘连的两个列名。
        # 只接受词起点对齐的情况，否则保守放弃列语义恢复。
        split_parts: Dict[int, List[str]] = {}
        for word in re.finditer(r"\S+", cell["text"]):
            word_left = cell["left"] + (right - cell["left"]) * word.start() / len(cell["text"])
            target = min(spanned, key=lambda i: abs(anchors[i] - word_left))
            if abs(anchors[target] - word_left) > _COLUMN_X_TOLERANCE:
                return None
            split_parts.setdefault(target, []).append(word.group())
        if set(split_parts) != set(spanned):
            return None
        for target, words in split_parts.items():
            parts[target].append(" ".join(words))
    labels = [re.sub(r"/\s+", "/", " ".join(part)).strip() for part in parts]
    if any(not label for label in labels) or len(set(labels)) != len(labels):
        return None
    return list(zip(anchors, labels))


def _code_row_column_values(
    row: List[Dict[str, Any]],
    columns: List[Tuple[float, str]],
) -> Optional[List[Dict[str, str]]]:
    """按列起点分配文本，保留空列；跨列粘连的正文不强行赋予列名。"""
    values: List[List[str]] = [[] for _ in columns]
    for cell in row:
        eligible = [i for i, (left, _) in enumerate(columns)
                    if left <= cell["left"] + _COLUMN_X_TOLERANCE]
        if not eligible:
            return None
        column = eligible[-1]
        right = cell.get("right")
        if column + 1 < len(columns) and right is not None \
                and right > columns[column + 1][0] + _COLUMN_X_TOLERANCE:
            return None
        values[column].append(cell["text"])
    return [{"column": label, "value": " ".join(values[i])}
            for i, (_, label) in enumerate(columns)]


def build_code_table_chunks_from_docling_json(
    docling_json_path: Any,
    filename: str = "",
) -> List[Dict[str, Any]]:
    """从 Docling JSON 坐标流恢复被压平成单列文本的代码表行。

    某些 PDF 表格在 markdown/tables.json 中会退化为一整行文本，但 Docling
    JSON 仍保留每个单元格的文本、横坐标和纵坐标。本函数以 ``Table N``
    表题为边界，识别表格最左列中的短代码，并把该代码到下一代码之间的
    单元格恢复为独立 ``table_row`` 分块，并按横坐标绑定列名、保留空列。
    无法可靠恢复列关系时明确标记不确定。规则只依赖表格结构，不内置任何
    Visa 字段或代码值，因此也适用于响应码、处理码、原因码和结果码表。
    """
    if not docling_json_path:
        return []
    path = Path(docling_json_path)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    texts = raw.get("texts") if isinstance(raw, dict) else None
    if not isinstance(texts, list):
        return []

    chunks: List[Dict[str, Any]] = []
    seen: set = set()
    for index, caption in enumerate(texts):
        title = str(caption.get("text") or "").strip()
        if caption.get("label") not in {"caption", "section_header"} \
                or not _TABLE_TITLE.match(title) or not _CODE_TABLE_TITLE.search(title):
            continue
        page_no, _ = _first_provenance(caption)
        if page_no is None:
            continue

        # 同一页、同一表题后的正文单元格。遇到下一张表、章节或页脚即停止。
        cells: List[Dict[str, Any]] = []
        for item in texts[index + 1:]:
            item_page, bbox = _first_provenance(item)
            label = item.get("label")
            value = str(item.get("text") or "").strip()
            if item_page != page_no:
                break
            if label in {"page_footer", "page_header"}:
                break
            if label in {"caption", "section_header"} and value:
                break
            if label != "text" or not value or not bbox:
                continue
            try:
                left = float(bbox.get("l"))
                top = float(bbox.get("t"))
                right = float(bbox["r"]) if bbox.get("r") is not None else None
            except (TypeError, ValueError):
                continue
            if not math.isfinite(left) or not math.isfinite(top) \
                    or (right is not None and (not math.isfinite(right) or right < left)):
                continue
            cells.append({"text": value, "left": left, "top": top, "right": right})

        if len(cells) < 4:
            continue
        left_edge = min(cell["left"] for cell in cells)
        starts = [
            position for position, cell in enumerate(cells)
            if cell["left"] <= left_edge + 18.0 and _CODE_CELL.fullmatch(cell["text"])
        ]
        # 单行误判的风险高；代码表通常至少有两行，少于两行交给普通分块。
        if len(starts) < 2:
            continue

        parent = _nearest_section_heading(texts, index)
        name = title if not parent or parent.casefold() in title.casefold() \
            else f"{parent} > {title}"
        # Field 编号可能位于表题后的表头单元格，而不在 caption 中。
        header_text = " ".join(cell["text"] for cell in cells[:starts[0]])
        field_match = _FIELD_NUMBER.search(f"{name} {header_text}")
        field_no = field_match.group(1) if field_match else ""
        row_groups = [cells[start:starts[i + 1] if i + 1 < len(starts) else len(cells)]
                      for i, start in enumerate(starts)]
        columns = _recover_code_table_columns(cells[:starts[0]], row_groups)

        for row_cells in row_groups:
            code = row_cells[0]["text"]
            values = [cell["text"] for cell in row_cells[1:] if cell["text"]]
            if not values:
                continue
            column_values = _code_row_column_values(row_cells, columns) if columns else None
            if column_values:
                row_text = " | ".join(
                    f"{item['column']}: {item['value'] or '原表空白（未给值）'}"
                    for item in column_values
                )
            else:
                row_text = " | ".join(values)
            identity = (name.casefold(), page_no, code.casefold(), row_text.casefold())
            if identity in seen:
                continue
            seen.add(identity)
            content = (
                f"[代码表行] {name}\n"
                f"代码: {code} | 内容: {row_text}\n"
                f"行描述: 在「{name}」中，代码 {code} 对应 {row_text}。"
            )
            if not column_values:
                content += "\n列关系未可靠恢复；以上为原始文本，不能按非空值顺序推断列含义。"
            chunks.append({
                "content": content,
                "tokens": max(1, len(content) // 2),
                "modality": "table_row",
                "table_name": name,
                "field_no": field_no,
                "code_value": code,
                "page_no": page_no,
                "source_filename": filename,
                "column_values": column_values or [],
                "column_alignment": "recovered" if column_values else "uncertain",
            })
    return chunks


def merge_derived_table_chunks(
    existing: List[Dict[str, Any]],
    derived: List[Dict[str, Any]],
) -> Tuple[int, int]:
    """续跑时原位更新同一代码表行，返回（新增数，更新数）。

    内容排重只能识别完全相同的版本。列恢复后内容会变化，故仅对具有
    唯一表名、页号及代码的代码表行使用稳定身份；正文和其他表格块仍
    只按内容排重。保留原分块 ID/顺序，避免把新版再追加为第二份证据。
    """
    def normalize(chunk: Dict[str, Any]) -> str:
        return " ".join(str(chunk.get("content") or "").split()).casefold()

    def identity(chunk: Dict[str, Any]) -> Optional[Tuple[str, int, str]]:
        if chunk.get("modality") != "table_row" \
                or not str(chunk.get("content") or "").startswith("[代码表行]"):
            return None
        name, page, code = chunk.get("table_name"), chunk.get("page_no"), chunk.get("code_value")
        if not name or not isinstance(page, int) or not code:
            return None
        return str(name).casefold(), page, str(code).casefold()

    known = {normalize(chunk) for chunk in existing if normalize(chunk)}
    positions: Dict[Tuple[str, int, str], List[int]] = {}
    for i, chunk in enumerate(existing):
        key = identity(chunk)
        if key:
            positions.setdefault(key, []).append(i)
    # 不为同一表中重复代码的不同记录猜测对应关系。
    derived_counts: Dict[Tuple[str, int, str], int] = {}
    for chunk in derived:
        key = identity(chunk)
        if key:
            derived_counts[key] = derived_counts.get(key, 0) + 1

    appended = updated = 0
    for chunk in derived:
        content = normalize(chunk)
        if not content or content in known:
            continue
        key = identity(chunk)
        matches = positions.get(key, []) if key else []
        if matches and (len(matches) != 1 or derived_counts.get(key) != 1):
            LOGGER.warning(f"代码表行身份不唯一, 保留历史记录且不追加新版: {key}")
            continue
        if len(matches) == 1 and derived_counts.get(key) == 1:
            index = matches[0]
            old = existing[index]
            replacement = {**old, **chunk}
            for preserved in ("id", "chunk_id", "chunk_order_index"):
                if preserved in old:
                    replacement[preserved] = old[preserved]
            # 内容改变后旧向量/检索文本失效，由调用方重新嵌入和建索引。
            replacement.pop("vector", None)
            replacement.pop("search_text", None)
            existing[index] = replacement
            known.add(content)
            updated += 1
        else:
            replacement = dict(chunk)
            replacement["chunk_order_index"] = len(existing)
            existing.append(replacement)
            if key:
                positions.setdefault(key, []).append(len(existing) - 1)
            known.add(content)
            appended += 1
    return appended, updated


def _parse_markdown_pipe_table(table_text: str) -> List[List[str]]:
    """解析单个 GFM pipe-table 文本为二维列表。

    自动跳过仅含 |---| 的分隔行; 单元格去除首尾空白。
    """
    rows: List[List[str]] = []
    for line in table_text.strip().splitlines():
        line = line.strip()
        if not _PIPE_ROW.match(line):
            continue
        # 跳过纯分隔行（|---|----|）
        cells_raw = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r"[-: ]+", c) for c in cells_raw):
            continue
        rows.append(cells_raw)
    return rows


def _h2_has_body_text(lines: List[str], h2_line: int, next_h2_line: int) -> bool:
    """检查 H2 标题后、下一个 H2 前是否有正文段落（非空行、非标题、非表格）。"""
    if h2_line < 0:
        return True  # 第一个 H2, 默认认为有正文
    for li in range(h2_line + 1, min(next_h2_line, len(lines))):
        stripped = lines[li].strip()
        if not stripped:
            continue
        if stripped.startswith("#") or _PIPE_ROW.match(stripped):
            continue
        # 找到了非标题、非表格行的内容 → 有正文
        return True
    return False


# 表名长度上限: 表名在行级块里出现两次（[表格行] 行与行描述）, 过长的
# 祖先链会稀释行数据的嵌入信号。大纲模式超限时逐级丢弃中间层级（保留
# 首尾: 顶层锚点与表题区分度最高）; 回落模式超限则放弃前置锚点。
# 阈值须容纳"章节 > 节 > 小节 > 表题"四级路径的常见长度（深层章节标题
# 本身可达 60+ 字符, 四级路径实测最长约 225）——过低会把中间层级裁掉,
# 造成同节下平级小节的同名表格碰撞, 比名字略长的代价大得多
_ANCHOR_NAME_MAXLEN = 240

# 锚点模式编译缓存: (配置原文, 编译结果), 配置变更才重新编译
_ANCHOR_CACHE_SRC: str = "\x00"  # 不可能与任何真实配置相同的哨兵
_ANCHOR_CACHE_PAT: Optional["re.Pattern"] = None

# 大纲配置编译缓存: (配置指纹, 编译结果), 配置变更才重新编译
_OUTLINE_CACHE_KEY: Optional[tuple] = None
_OUTLINE_CACHE_VAL: Optional[tuple] = None


def _get_anchor_pattern() -> Optional["re.Pattern"]:
    """编译并缓存表格命名锚点模式; 配置为空 → None（禁用锚点回溯）。

    非法正则不回退静默: 退回内置默认模式并告警——锚点回溯是检索可达性
    特性, 配置笔误时保持特性可用比直接关闭更符合预期。
    """
    global _ANCHOR_CACHE_SRC, _ANCHOR_CACHE_PAT
    pat_str = PROJECT_CONFIG.TABLE_ANCHOR_PATTERN or ""
    if not pat_str:
        return None
    if _ANCHOR_CACHE_SRC == pat_str:
        return _ANCHOR_CACHE_PAT
    try:
        compiled = re.compile(pat_str)
    except re.error as exc:
        LOGGER.warning(
            f"TABLE_ANCHOR_PATTERN 非法({exc}), 回退内置默认模式: {exc}"
        )
        compiled = re.compile(r"\b[A-Z]{2,6}\s*\d+")
    _ANCHOR_CACHE_SRC = pat_str
    _ANCHOR_CACHE_PAT = compiled
    return compiled


def _get_outline_config() -> Optional[tuple]:
    """编译并缓存语义大纲配置; TABLE_OUTLINE_LEVELS 为空 → None（禁用大纲模式）。

    :return: (层级正则表, 重置正则或 None, 样板标题停用集合) 或 None

    单个层级正则非法时告警并跳过该层级（其余层级照常生效）——大纲命名
    是检索可达性特性, 部分配置笔误时保留可用层级比整体静默关闭更符合预期。
    """
    global _OUTLINE_CACHE_KEY, _OUTLINE_CACHE_VAL
    levels = tuple(PROJECT_CONFIG.TABLE_OUTLINE_LEVELS or [])
    stoplist = tuple(PROJECT_CONFIG.TABLE_HEADING_STOPLIST or [])
    reset = PROJECT_CONFIG.TABLE_OUTLINE_RESET_PATTERN or ""
    key = (levels, stoplist, reset)
    if _OUTLINE_CACHE_KEY == key:
        return _OUTLINE_CACHE_VAL
    if not levels:
        _OUTLINE_CACHE_KEY, _OUTLINE_CACHE_VAL = key, None
        return None
    compiled: List["re.Pattern"] = []
    for pat_str in levels:
        try:
            compiled.append(re.compile(pat_str, re.IGNORECASE))
        except re.error as exc:
            LOGGER.warning(
                f"TABLE_OUTLINE_LEVELS 模式非法({pat_str}: {exc}), 跳过该层级"
            )
    reset_pat: Optional["re.Pattern"] = None
    if reset:
        try:
            reset_pat = re.compile(reset, re.IGNORECASE)
        except re.error as exc:
            LOGGER.warning(
                f"TABLE_OUTLINE_RESET_PATTERN 非法({exc}), 忽略重置配置"
            )
    stop_set = frozenset(s.strip().lower() for s in stoplist if s and s.strip())
    _OUTLINE_CACHE_KEY, _OUTLINE_CACHE_VAL = key, (compiled, reset_pat, stop_set)
    return _OUTLINE_CACHE_VAL


def _fit_name_budget(parts: List[str]) -> str:
    """大纲全路径长度预算: 超限时从靠近表题一端逐个丢弃中间层级, 保留首尾。

    首段（顶层锚点, 如 DE 级章节）与末段（表题）区分度最高; 牺牲顺序为
    节 context → 较深角色层级, 即先丢离表题最近的中间层; 只剩两段后即使
    超限也保留——表题本身不可丢弃。
    """
    name = " > ".join(parts)
    while len(name) > _ANCHOR_NAME_MAXLEN and len(parts) > 2:
        parts.pop(-2)
        name = " > ".join(parts)
    return name


def _compose_table_heading(
        outline_cfg: Optional[tuple],
        outline_stack: List[tuple],
        prev_heading: str,
        context_heading: str,
        h2_heading: str,
        prev_h2_heading: str,
        recent_headings: List[str],
        anchor_pat: Optional["re.Pattern"],
) -> str:
    """表格层级表名合成: 优先语义大纲全路径, 栈空回落两槽位+锚点回溯。

    大纲模式（outline_cfg 非空且栈非空）: 栈内祖先（章节 > 小节 > …）+
    节 context（本节内最近的非样板标题, 如 Subelement 分组）+ 表格前导标题
    （表题）拼成完整定位路径; 相邻段落同文本时去重。
    回落路径: 原有两槽位（最近标题 + 上层 H2）+ 窗口锚点回溯, 用于未配置
    大纲层级或表格处大纲栈为空（如文档尾部无角色标题的区域）。
    """
    if outline_cfg is not None and outline_stack:
        parts = [text for _depth, text in outline_stack]
        if context_heading and context_heading != prev_heading \
                and context_heading != parts[-1]:
            parts.append(context_heading)
        if prev_heading and prev_heading != parts[-1]:
            parts.append(prev_heading)
        return _fit_name_budget(parts)
    # 回落: 两槽位层级表名
    full_heading = prev_heading
    if prev_heading != h2_heading and h2_heading:
        # H3/H4 表格: 带上层 H2 节名
        full_heading = f"{h2_heading} > {prev_heading}"
    elif prev_h2_heading and prev_h2_heading != h2_heading:
        # H2 表格: 带上一个 H2 作为章节语境
        full_heading = f"{prev_h2_heading} > {prev_heading}"
    # 锚点回溯: 取窗口内最近的编号型锚点标题前置（只取最近一个,
    # 无论是否前置成功都在首个命中处停止——更远的锚点不属于本表的祖先）。
    # 已在表名中的锚点不重复前置; 前置后超长则放弃
    if anchor_pat is not None and full_heading:
        for h in reversed(recent_headings):
            if anchor_pat.search(h):
                if h not in full_heading and \
                        len(h) + 3 + len(full_heading) <= _ANCHOR_NAME_MAXLEN:
                    full_heading = f"{h} > {full_heading}"
                break
    return full_heading


def _find_markdown_tables(markdown: str) -> List[Dict[str, Any]]:
    """从 markdown 文本中提取所有 GFM pipe-table, 返回结构化列表。

    每项包含:
    - heading: 层级表名（含锚点前缀, 见下; 作为表名候选）
    - parent_heading: 表格的上层标题（如 H2 下的 H3 表格, parent_heading 为 H2）
    - headers: 表头列表
    - rows: 数据行列表（每行为字符串列表）
    - start: 在原文中的行号位置

    识别规则: 连续 ≥2 个 pipe-row（表头 + 分隔行）即判定为一组表格,
    后续 pipe-row 视为数据行, 遇到空行/非 pipe 行则结束该表格。

    表名层级构建（语义大纲栈优先, 两槽位回落）:
    1. 大纲模式（TABLE_OUTLINE_LEVELS 非空）: 标题命中第 k 个层级正则即
       判定为深度 k 的角色标题（如 DE=章节, Subfield=小节）, 弹栈至深度<k
       后压栈; 命中重置模式（TABLE_OUTLINE_RESET_PATTERN, 附录等）清空栈;
       样板标题（TABLE_HEADING_STOPLIST, 如 Values/Attributes）不进祖先链。
       表格命名 = 栈内祖先 + 节 context + 表格前导标题（表题）, 得到
       "章节 > 小节 > … > 表题"的完整定位路径。节 context 是本节内最近的
       非角色/非样板标题（如 Subelement 分组）, 随角色/重置标题清空,
       用于区分同一小节下平级分组里的同名表格; 已被借作表题的标题按保守
       语义不再作后续表格的 context（见 ctx1_consumed）。角色标题的作用域
       由压栈纪律天然界定——锚点存活到下一个同级/更高级角色标题为止,
       不受中间节数量影响, 无窗口超窗问题;
    2. 回落路径（大纲未配置, 或表格处栈为空）: 两槽位层级（最近标题 +
       上层 H2）+ 锚点回溯（最近 N 个标题窗口内倒序找第一个命中
       TABLE_ANCHOR_PATTERN 的"字段定义锚点"标题前置到表名）。
    """
    # 预编译: 分隔行判定——去除 |、空格、连字符、冒号后应为空字符串
    _SEP_CLEAN = re.compile(r"[\s\-:|]+")

    lines = markdown.splitlines()
    tables: List[Dict[str, Any]] = []
    i = 0
    h2_heading = ""        # 当前 H2 节标题
    prev_h2_heading = ""   # 上一个有实质内容的 H2 节标题（跳过相邻的叶子 H2）
    prev_heading = ""      # 表格前最近的标题（任意层级）
    h2_start_line = -1     # 当前 H2 在 lines 中的行号（用于正文检测）
    recent_headings: List[str] = []   # 最近标题窗口（锚点回溯用, 含当前标题）
    anchor_pat = _get_anchor_pattern()
    scan_window = PROJECT_CONFIG.TABLE_ANCHOR_SCAN_WINDOW
    outline_cfg = _get_outline_config()      # 语义大纲配置（None = 大纲模式禁用）
    outline_stack: List[tuple] = []          # (深度, 标题文本) 语义大纲栈
    ctx1 = ""  # 本节内最近的合格 context 标题（非角色/非样板/非重置）
    ctx2 = ""  # 次近的合格 context 标题（表题本身合格时让位为 context）
    ctx1_consumed = False  # ctx1 已被某表借作表题: 退位 ctx2 时须丢弃。
    # 扁平文档中借题标题是平级兄弟（Debits 之于 Credits, 不应作祖先）还是
    # 包裹节（消息节标题借出结构表后仍包裹后续小节）无法可靠区分——二者
    # 结构同形; 取保守语义: 宁失包裹语境, 不造错误祖先
    while i < len(lines):
        stripped = lines[i].strip()
        # 追踪标题层级
        if stripped.startswith("#"):
            level = len(re.match(r"^#+", stripped).group())
            heading_text = re.sub(r"^#+\s*", "", stripped).strip()
            if level <= 2:
                # 检查上一个 H2 后是否有正文内容（不只是空行+表格）;
                # 没有正文的叶子 H2 不提升为 parent, 保持真正的章节锚点
                has_body = _h2_has_body_text(lines, h2_start_line, i)
                if has_body or not prev_h2_heading:
                    prev_h2_heading = h2_heading
                h2_heading = heading_text
                h2_start_line = i
            prev_heading = heading_text
            # 锚点窗口: 只保留最近 scan_window 个标题
            recent_headings.append(heading_text)
            if len(recent_headings) > scan_window:
                recent_headings.pop(0)
            # 语义大纲维护（判定顺序: 重置 → 样板 → 角色 → 普通）:
            # - 重置标题（附录等）: 清栈并清空节 context;
            # - 样板标题（Values/Attributes 等）: 不进祖先链也不作 context,
            #   仅可作表题; 先于层级匹配判定, 宽松正则下防样板混入祖先链;
            # - 角色标题: 按深度压栈（弹掉同级/更低层级）, 新节开始 → 清空
            #   上一节的 context 槽, 防跨节语境污染;
            # - 普通标题: 移入节 context 槽（最近/次近）, 命名时作为栈与表题
            #   之间的中间定位层（如 Subelement 分组）
            if outline_cfg is not None:
                level_pats, reset_pat, stoplist = outline_cfg
                if reset_pat is not None and reset_pat.search(heading_text):
                    outline_stack.clear()
                    ctx1 = ctx2 = ""
                    ctx1_consumed = False
                elif heading_text.strip().lower() in stoplist:
                    pass
                else:
                    role_depth = 0
                    for depth, pat in enumerate(level_pats, start=1):
                        if pat.search(heading_text):
                            role_depth = depth
                            break
                    if role_depth:
                        while outline_stack and outline_stack[-1][0] >= role_depth:
                            outline_stack.pop()
                        outline_stack.append((role_depth, heading_text))
                        ctx1 = ctx2 = ""
                        ctx1_consumed = False
                    else:
                        # 旧 ctx1 若已被借作表题, 按保守语义不得退位为 ctx2
                        # （见 ctx1_consumed 注释）
                        ctx2 = "" if ctx1_consumed else ctx1
                        ctx1, ctx1_consumed = heading_text, False
        # 表格起始: 当前行是 pipe-row, 下一行是分隔行
        if _PIPE_ROW.match(stripped) and i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            sep_cleaned = _SEP_CLEAN.sub("", next_stripped.strip("|"))
            if _PIPE_ROW.match(next_stripped) and sep_cleaned == "":
                j = i
                table_lines: List[str] = []
                while j < len(lines) and _PIPE_ROW.match(lines[j].strip()):
                    table_lines.append(lines[j].strip())
                    j += 1
                table_text = "\n".join(table_lines)
                rows = _parse_markdown_pipe_table(table_text)
                if len(rows) >= 2:  # 至少 header + 1 行数据
                    # 层级表名: 让表名包含文档节上下文（章节 > 小节 > … > 表题）,
                    # 提升不同节同名表格的区分度; 大纲栈空时回落两槽位+锚点回溯。
                    # 节 context 取舍: 表题本身是合格 context 标题（=ctx1）时,
                    # 让次近标题作 context, 否则用最近合格标题
                    context_heading = ""
                    title_is_ctx1 = bool(
                        outline_cfg is not None and prev_heading and prev_heading == ctx1
                    )
                    if outline_cfg is not None and outline_stack:
                        context_heading = ctx2 if title_is_ctx1 else ctx1
                    full_heading = _compose_table_heading(
                        outline_cfg, outline_stack, prev_heading, context_heading,
                        h2_heading, prev_h2_heading, recent_headings, anchor_pat,
                    )
                    # 表题消费纪律: 标题已被用作某表的表题后, 打 consumed 标记——
                    # 它仍可作自身子表（Values 等）的 context（仍是 ctx1）, 但
                    # 下一个合格标题到来时不得退位为 ctx2 去包裹平级兄弟
                    # （如 Debits 表题不应进入相邻 Credits 表的路径, TAG 83
                    # 表题不应顶替 TAG 86 的位置）。标题仅作 context（表题另有
                    # 其题）时不消费, 同一分组标题可继续覆盖其下多张表
                    if title_is_ctx1 and outline_stack:
                        ctx1_consumed = True
                    tables.append({
                        "heading": full_heading,
                        "parent_heading": prev_h2_heading,
                        "headers": rows[0],
                        "rows": rows[1:],
                        "start": i,
                    })
                i = j
                continue
        i += 1
    return tables


def _table_signature(headers: List[str], rows: List[List[str]]) -> str:
    """为表格生成排重签名: 列数 × 行数 + 表头 + 首行 + 末行, 归一化后哈希。"""
    norm = lambda s: s.strip().lower().replace(" ", "")
    parts = [
        f"cols={len(headers)}",
        f"rows={len(rows)}",
        "h:" + "|".join(norm(c) for c in headers),
        "r0:" + "|".join(norm(c) for c in rows[0]) if rows else "",
        "rm:" + "|".join(norm(c) for c in rows[-1]) if len(rows) > 1 else "",
    ]
    return "|".join(parts)


def build_table_chunks_from_markdown(
    markdown: str,
    tables_path: Any = None,
    filename: str = "",
) -> List[Dict[str, Any]]:
    """扫描 markdown 文本中的 GFM pipe-table, 为不在 tables.json 中的表格
    生成表级摘要块 + 行级块。

    用于补救 docling 未识别为 table 对象的 markdown 表格（如 PDF 中以纯文本
    形式存在的 pipe-table）, 使它们与 docling 识别的表格获得同等的检索粒度。

    :param markdown: 清洗后的 markdown 全文
    :param tables_path: tables.json 路径, 用于排重; 为空则不去重
    :param filename: 文档文件名
    :return: 分块字典列表
    """
    if not markdown:
        return []

    # 加载已识别表格的签名集合（排重用）
    existing_sigs: set = set()
    if tables_path:
        path = Path(tables_path)
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                existing_tables = raw.get("tables", {}) if isinstance(raw, dict) else {}
                if isinstance(existing_tables, dict):
                    for entry in existing_tables.values():
                        if not isinstance(entry, dict):
                            continue
                        html_rows = parse_html_table(entry.get("body", ""))
                        if len(html_rows) >= 2:
                            sig = _table_signature(html_rows[0], html_rows[1:])
                            existing_sigs.add(sig)
            except (OSError, json.JSONDecodeError):
                pass

    md_tables = _find_markdown_tables(markdown)
    if not md_tables:
        return []

    stem = Path(filename).stem if filename else ""
    chunks: List[Dict[str, Any]] = []
    ordinal = 0

    for tbl in md_tables:
        headers = tbl["headers"]
        rows = tbl["rows"]
        if len(rows) == 0:
            continue
        # 排重: 与 tables.json 中已存在的表格比对
        sig = _table_signature(headers, rows)
        if sig in existing_sigs:
            continue
        existing_sigs.add(sig)

        ordinal += 1
        width = len(headers)
        labels = _header_labels(headers, width)
        total = len(rows)
        # 表名: 优先用前导标题, 否则回退文件名
        name = tbl["heading"] or f"{stem or '文档'} 表 (markdown) {ordinal}"

        # ---- 表级摘要块 ----
        summary = (
            f"[表格] {name}（{total} 行 × {width} 列）\n"
            f"列: {', '.join(labels)}\n"
            f"概述: 本表来自文档 {filename or '-'}，共 {total} 行数据、"
            f"{width} 列（{' / '.join(labels)}），逐行列出表格内容。"
        )
        chunks.append({
            "content": summary,
            "tokens": max(1, len(summary) // 2),
            "modality": "table",
        })

        # ---- 行级块 ----
        for i, cells in enumerate(rows, start=1):
            values = [(cells[j].strip() if j < len(cells) else "") for j in range(width)]
            if not any(values):
                continue
            structured = " | ".join(f"{labels[j]}: {values[j]}" for j in range(width))
            pairs = [f"{labels[j]} 为 {values[j]}" for j in range(width) if values[j]]
            joined = "；".join(pairs)
            if joined and joined[-1] not in ".。!！?？":
                joined += "。"
            content = (
                f"[表格行] {name} · 第 {i} 行/共 {total} 行\n"
                f"{structured}\n"
                f"行描述: 在「{name}」表格的第 {i} 行中：{joined}"
            )
            chunks.append({
                "content": content,
                "tokens": max(1, len(content) // 2),
                "modality": "table_row",
            })

    return chunks


# 匹配完整的 GFM pipe-table: 表头行 + 分隔行 + 数据行
_TABLE_BLOCK = re.compile(
    r"^\|.+\|\s*\n"           # header line
    r"^\|[\s\-:|]+\|\s*\n"    # separator line
    r"(?:^\|.+\|\s*\n?)+",    # one or more data lines
    re.MULTILINE,
)


def strip_markdown_tables(markdown: str) -> str:
    """将 markdown 中的 pipe-table 替换为简短占位符, 消除文本分块中的表格冗余。

    表中数据已通过 build_table_chunks / build_table_chunks_from_markdown
    生成了结构化分块, 文本分块只需保留上下文（表格的存在及主题）, 无需
    再嵌入原始 pipe-table 文本。

    :return: 替换后的 markdown 文本
    """
    if not markdown:
        return markdown

    # 先找出所有表格的位置和对应的 heading
    md_tables = _find_markdown_tables(markdown)
    # 按起始行排序, 从后往前替换以避免偏移问题
    lines = markdown.splitlines()

    # 构建 (起始行号, 结束行号, 原标题) 列表
    table_spans: List[Dict[str, Any]] = []
    for tbl in md_tables:
        # 定位表格在 lines 中的起止位置
        start_line = tbl["start"]
        # 表格行数: 1 表头行 + 1 分隔行 + N 数据行
        table_lines = 1 + 1 + len(tbl["rows"])
        end_line = start_line + table_lines
        heading = tbl.get("heading", "")
        # 构建占位符: 优先用原标题, 否则用行列数描述
        if heading:
            placeholder = (
                f"[表格: {heading} — {len(tbl['rows'])} 行 × {len(tbl['headers'])} 列，"
                f"结构化数据见表格分块]"
            )
        else:
            placeholder = (
                f"[表格: {len(tbl['rows'])} 行 × {len(tbl['headers'])} 列，"
                f"结构化数据见表格分块]"
            )
        table_spans.append({
            "start": start_line,
            "end": min(end_line, len(lines)),
            "placeholder": placeholder,
        })

    # 从后往前替换（保证行索引不变）
    for span in sorted(table_spans, key=lambda s: s["start"], reverse=True):
        # 替换表格行为占位符，保留表格前的空行和标题
        start = span["start"]
        end = span["end"]
        # 如果表格前一行是空行，也吞掉避免多余空行
        if start > 0 and lines[start - 1].strip() == "":
            start -= 1
        lines[start:end] = [span["placeholder"]]

    return "\n".join(lines)


def _build_heading_map(markdown: str) -> Dict[str, str]:
    """扫描 markdown 中所有 pipe-table, 构建 表格签名 → 前导标题 的映射。

    用于为 tables.json 中没有 caption 的表格补充章节上下文命名。
    """
    heading_map: Dict[str, str] = {}
    if not markdown:
        return heading_map
    for tbl in _find_markdown_tables(markdown):
        if not tbl["heading"] or len(tbl["rows"]) == 0:
            continue
        sig = _table_signature(tbl["headers"], tbl["rows"])
        heading_map[sig] = tbl["heading"]
    return heading_map


def build_table_chunks(
    tables_path: Any,
    filename: str = "",
    markdown_text: str = "",
) -> List[Dict[str, Any]]:
    """读取 sidecar tables.json, 为每张有效表格生成 1 个表级摘要块 + 若干行级块。

    过滤规则: 无数据行的表、单列目录表整体跳过; 全空数据行跳过。

    :param tables_path: tables.json 路径（sidecar.get("tables")）; 为空/不存在时返回 []
    :param filename: 文档文件名（表名回退命名用）
    :param markdown_text: 可选, 清洗后的 markdown 全文; 用于从章节标题为无
        caption 的表格补充命名, 提升检索时可读性
    :return: 分块字典列表（content/tokens/modality, 由调用方续编 chunk_order_index 后并入）
    """
    if not tables_path:
        return []
    path = Path(tables_path)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    tables = raw.get("tables", {}) if isinstance(raw, dict) else {}
    if not isinstance(tables, dict):
        return []

    # 预建标题映射: 用于为无 caption 的表格从 markdown 章节标题补名
    heading_map = _build_heading_map(markdown_text) if markdown_text else {}

    stem = Path(filename).stem if filename else ""
    chunks: List[Dict[str, Any]] = []
    ordinal = 0

    for tid in sorted(tables):
        entry = tables[tid]
        if not isinstance(entry, dict):
            continue
        rows = parse_html_table(entry.get("body", ""))
        if len(rows) < 2:
            continue  # 表头之外无数据行
        if is_toc_table(rows):
            continue  # 消费端兜底: 生成端已剔除的旧 sidecar 产物不再建块
        ordinal += 1

        header, data_rows = rows[0], rows[1:]
        width = max(len(header), *(len(r) for r in data_rows))
        labels = _header_labels(header, width)
        # 命名优先级: ① tables.json 的 caption  → ② markdown 章节标题 → ③ 兜底序号
        name = _table_name(entry, ordinal, stem)
        if name == f"{stem or '文档'} 表 {ordinal}" and heading_map:
            sig = _table_signature(header, data_rows)
            if sig in heading_map:
                name = heading_map[sig]
        total = len(data_rows)

        # ---- 表级摘要块（整表级检索兜底） ----
        summary = (
            f"[表格] {name}（{total} 行 × {width} 列）\n"
            f"列: {', '.join(labels)}\n"
            f"概述: 本表来自文档 {filename or '-'}，共 {total} 行数据、"
            f"{width} 列（{' / '.join(labels)}），逐行列出表格内容。"
        )
        chunks.append({
            "content": summary,
            "tokens": max(1, len(summary) // 2),
            "modality": "table",
        })

        # ---- 行级块（行数据 + 元数据 + 自然语言描述） ----
        for i, cells in enumerate(data_rows, start=1):
            values = [(cells[j].strip() if j < len(cells) else "") for j in range(width)]
            if not any(values):
                continue  # 全空行跳过
            structured = " | ".join(f"{labels[j]}: {values[j]}" for j in range(width))
            pairs = [f"{labels[j]} 为 {values[j]}" for j in range(width) if values[j]]
            joined = "；".join(pairs)
            if joined and joined[-1] not in ".。!！?？":
                joined += "。"
            content = (
                f"[表格行] {name} · 第 {i} 行/共 {total} 行\n"
                f"{structured}\n"
                f"行描述: 在「{name}」表格的第 {i} 行中：{joined}"
            )
            chunks.append({
                "content": content,
                "tokens": max(1, len(content) // 2),
                "modality": "table_row",
            })

    return chunks
