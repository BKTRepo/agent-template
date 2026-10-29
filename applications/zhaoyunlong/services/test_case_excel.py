"""将模型生成的 Markdown 测试用例表格转换为 Excel 文档。"""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font


class TestCaseExcelError(ValueError):
    """模型结果不能安全转换为测试用例 Excel 时抛出的异常。"""


_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")
_OUTPUT_HEADERS = [
    "案例id", "序号", "案例名称", "描述", "应用系统", "优先级", "正/反",
    "前置条件", "备注", "步骤", "预期值", "创建人", "创建时间", "维护人",
    "维护时间", "案例目录", "案例类型", "案例标签",
]


def build_test_case_workbook(markdown_path: Path, target_path: Path) -> int:
    """读取 Markdown 表格并生成 Excel；返回写入的测试用例数量。"""
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TestCaseExcelError("无法读取模型生成的测试用例 Markdown 文件") from exc

    rows = _extract_test_case_rows(markdown)
    if not rows:
        raise TestCaseExcelError("模型结果不包含可转换的 Markdown 测试用例表格")

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Sheet1"
    worksheet.sheet_format.defaultColWidth = 11
    worksheet.sheet_format.defaultRowHeight = 17.25
    worksheet.append(_OUTPUT_HEADERS)
    for index, row in enumerate(rows, start=1):
        # 与给定模板保持一致：案例 id 留空，序号由程序按实际行数生成。
        row[0] = ""
        row[1] = index
        worksheet.append(row)

    font = Font(name="等线", size=12, charset=134)
    for cell in worksheet[1]:
        cell.font = font
        cell.alignment = Alignment(vertical="center")
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = font
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            # 模型生成内容是业务文本，不能作为 Excel 公式执行。
            if isinstance(cell.value, str):
                cell.data_type = "s"
        worksheet.row_dimensions[row[0].row].height = 72
    for index, width in enumerate((20, 8, 32, 42, 18, 10, 11, 32, 30, 52, 42, 12, 14, 12, 14, 36, 14, 18), start=1):
        worksheet.column_dimensions[_column_letter(index)].width = width
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        workbook.save(target_path)
    except OSError as exc:
        raise TestCaseExcelError("无法保存调试结果 Excel 文档") from exc
    return len(rows)


def _extract_test_case_rows(markdown: str) -> list[list[str]]:
    """提取所有合法 Markdown 表格，将每个数据行视为一条测试用例。"""
    lines = markdown.splitlines()
    result: list[list[str]] = []
    index = 0
    while index + 1 < len(lines):
        header = _split_table_row(lines[index])
        separator = _split_table_row(lines[index + 1])
        if not header or not _is_separator(separator, len(header)):
            index += 1
            continue
        mapping = _header_mapping(header)
        index += 2
        # 跳过其他说明表格，避免把无关内容错误写入案例数据。
        if 2 not in mapping.values():
            continue
        while index < len(lines):
            values = _split_table_row(lines[index])
            if not values or len(values) != len(header):
                break
            normalized = ["" for _ in _OUTPUT_HEADERS]
            for source_index, target_index in mapping.items():
                normalized[target_index] = _normalize_cell(values[source_index])
            if any(normalized):
                result.append(normalized)
            index += 1
    return result


def _split_table_row(line: str) -> list[str] | None:
    """拆分一行 Markdown 表格，支持以反斜杠转义的竖线。"""
    text = line.strip()
    if not text.startswith("|") or text.count("|") < 2:
        return None
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in text[1:]:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if current:
        return None
    return cells


def _is_separator(cells: list[str] | None, expected_length: int) -> bool:
    """判断 Markdown 表头后的分隔行。"""
    return bool(cells and len(cells) == expected_length and all(_SEPARATOR_CELL.fullmatch(cell) for cell in cells))


def _header_mapping(headers: list[str]) -> dict[int, int]:
    """把模型表头映射为 ATPM 模板列，兼容此前的十列表头。"""
    normalized = [_normalize_header(header) for header in headers]
    mapping: dict[int, int] = {}
    aliases = {
        0: {"案例id", "测试用例id", "用例id", "caseid", "编号", "id"},
        1: {"序号"},
        2: {"案例名称", "测试用例标题", "用例标题", "标题", "名称"},
        3: {"描述", "测试用例描述", "用例描述", "案例描述"},
        4: {"应用系统", "系统名称"},
        5: {"优先级", "优先程度"},
        6: {"正/反", "正/反案例", "正反案例", "案例性质", "正向/反向"},
        7: {"前置条件", "前提条件"},
        8: {"备注", "说明", "注释"},
        9: {"步骤", "测试步骤", "操作步骤"},
        10: {"预期值", "预期结果", "期望结果", "预期"},
        11: {"创建人"},
        12: {"创建时间"},
        13: {"维护人"},
        14: {"维护时间"},
        15: {"案例目录", "用例目录"},
        16: {"案例类型", "测试类型"},
        17: {"案例标签", "用例标签", "标签"},
    }
    aliases = {column: {_normalize_header(name) for name in names} for column, names in aliases.items()}
    for source_index, header in enumerate(normalized):
        target = next((column for column, names in aliases.items() if header in names), None)
        if target is not None and target not in mapping.values():
            mapping[source_index] = target
    return mapping


def _normalize_header(value: str) -> str:
    """标准化模型给出的表头文字。"""
    return re.sub(r"[\s_\-：:]", "", value).lower()


def _normalize_cell(value: str) -> str:
    """将 Markdown 单元格内容转成适合 Excel 换行展示的普通文本。"""
    return value.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n").strip()


def _column_letter(index: int) -> str:
    """把一位列序号转为 Excel 列名。"""
    return chr(ord("A") + index - 1)
