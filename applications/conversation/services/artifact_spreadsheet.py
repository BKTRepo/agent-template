"""Read worksheet pages and patch cells in their original worksheet parts."""

from datetime import date, time, timedelta
from io import BytesIO
from math import isfinite
from posixpath import normpath
from typing import Literal
from zipfile import ZipFile

from fastapi import HTTPException
from lxml import etree
from openpyxl import load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE, MergedCell
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter
from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr

from .artifact_ooxml import check_package, rewrite_package, xml_bytes, xml_root

S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
WORKBOOK = "xl/workbook.xml"
WORKBOOK_RELS = "xl/_rels/workbook.xml.rels"


class CellEdit(BaseModel):
    sheet_index: int = Field(ge=0)
    address: str = Field(pattern=r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")
    type: Literal["text", "number", "boolean", "formula", "blank"]
    value: StrictStr | StrictInt | StrictFloat | StrictBool | None


def _load(content):
    check_package(content)
    try:
        return load_workbook(BytesIO(content), data_only=False, rich_text=True)
    except Exception as exc:
        raise HTTPException(422, "XLSX 无法读取") from exc


def sheet_metadata(content):
    book = _load(content)
    try:
        return [{"index": index, "name": sheet.title, "rows": sheet.max_row, "columns": sheet.max_column}
                for index, sheet in enumerate(book.worksheets) if sheet.sheet_state == "visible"]
    finally:
        book.close()


def _sheet(book, index):
    if index >= len(book.worksheets) or book.worksheets[index].sheet_state != "visible":
        raise HTTPException(404, "工作表不可用")
    return book.worksheets[index]


def sheet_page(content, index, offset, column_offset, limit, column_limit):
    book = _load(content)
    try:
        sheet = _sheet(book, index)
        # Include a spare row and column for appending values without rewriting the sheet layout.
        end_row = min(offset + limit, sheet.max_row + 1, 1048576)
        end_column = min(column_offset + column_limit, sheet.max_column + 1, 16384)
        columns = range(column_offset + 1, end_column + 1)
        rows = [[_cell_display(sheet.cell(row, column), sheet.protection.sheet) for column in columns]
                for row in range(offset + 1, end_row + 1)]
        return {"offset": offset, "column_offset": column_offset, "rows": rows,
                "columns": [get_column_letter(column) for column in columns]}
    finally:
        book.close()


def _cell_display(cell, protected):
    value = cell.value
    if value is None:
        kind = "blank"
    elif cell.data_type == "f":
        kind = "formula"
    elif isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, (int, float)) and isfinite(value):
        kind = "number"
    elif isinstance(value, (date, time, timedelta)) or cell.data_type == "e":
        kind = "read_only"
        value = str(value)
    else:
        kind = "text"
        value = str(value)
    if kind == "formula" and not isinstance(value, str):
        kind, value = "read_only", getattr(value, "text", None) or "数组或数据表公式"
    return {"address": cell.coordinate, "value": value, "type": kind,
            "editable": kind != "read_only" and not isinstance(cell, MergedCell) and not (protected and cell.protection.locked),
            "bold": bool(cell.font.bold)}


def _set_value(cell, edit):
    value = edit.value
    cell.attrib.pop("t", None)
    for tag in ("f", "v", "is"):
        node = cell.find(S + tag)
        if node is not None:
            cell.remove(node)
    # Cell extension nodes must stay last.
    def insert(tag, text=None, **attributes):
        node = etree.Element(S + tag, **attributes)
        node.text = text
        last = cell.find(S + "extLst")
        cell.insert(cell.index(last) if last is not None else len(cell), node)
        return node

    if edit.type == "blank" and value is None:
        return
    if edit.type == "text" and isinstance(value, str) and len(value) <= 32767 and not ILLEGAL_CHARACTERS_RE.search(value):
        cell.set("t", "inlineStr")
        inline = insert("is")
        etree.SubElement(inline, S + "t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = value
    elif edit.type == "number" and type(value) in (int, float) and isfinite(value):
        insert("v", str(value))
    elif edit.type == "boolean" and type(value) is bool:
        cell.set("t", "b")
        insert("v", "1" if value else "0")
    elif edit.type == "formula" and isinstance(value, str) and value.startswith("=") and 1 < len(value) <= 8192 and not ILLEGAL_CHARACTERS_RE.search(value):
        insert("f", value[1:])
    else:
        raise HTTPException(422, f"单元格 {edit.address} 的值与数据类型不匹配")


def _patch_sheet(root, sheet, edits):
    sheet_data = root.find(S + "sheetData")
    rows = {int(row.get("r")): row for row in sheet_data.findall(S + "row")}
    for edit in edits:
        row_number, column = coordinate_to_tuple(edit.address)
        if row_number > 1048576 or column > 16384:
            raise HTTPException(422, "单元格超出工作表范围")
        original = sheet.cell(row_number, column)
        if not _cell_display(original, sheet.protection.sheet)["editable"]:
            raise HTTPException(422, f"单元格 {edit.address} 当前为只读")
        row = rows.get(row_number)
        if row is None:
            row = etree.Element(S + "row", r=str(row_number))
            next_row = next((item for number, item in sorted(rows.items()) if number > row_number), None)
            sheet_data.insert(sheet_data.index(next_row) if next_row is not None else len(sheet_data), row)
            rows[row_number] = row
        row.attrib.pop("spans", None)
        cells = row.findall(S + "c")
        target = next((cell for cell in cells if cell.get("r") == edit.address), None)
        if target is None:
            target = etree.Element(S + "c", r=edit.address)
            after = next((cell for cell in cells if coordinate_to_tuple(cell.get("r"))[1] > column), row.find(S + "extLst"))
            row.insert(row.index(after) if after is not None else len(row), target)
        formula = target.find(S + "f")
        if formula is not None and formula.get("t") in {"shared", "array", "dataTable"}:
            raise HTTPException(422, f"单元格 {edit.address} 含共享、数组或数据表公式，当前为只读")
        _set_value(target, edit)
    dimension = root.find(S + "dimension")
    if dimension is not None:
        dimension.set("ref", sheet.calculate_dimension())


def _part(target):
    return target.lstrip("/") if target.startswith("/") else normpath("xl/" + target)


def save_sheet(content: bytes, edits: list[CellEdit]) -> bytes:
    book = _load(content)
    try:
        grouped = {}
        for edit in edits:
            addresses = grouped.setdefault(edit.sheet_index, {})
            if edit.address in addresses:
                raise HTTPException(422, "单元格变更不能重复")
            addresses[edit.address] = edit
        with ZipFile(BytesIO(content)) as archive:
            workbook = xml_root(archive.read(WORKBOOK))
            relations = xml_root(archive.read(WORKBOOK_RELS))
            by_id = {node.get("Id"): _part(node.get("Target")) for node in relations
                     if node.get("TargetMode") != "External"}
            by_name = {node.get("name"): by_id.get(node.get(R + "id")) for node in workbook.find(S + "sheets")}
            replacements = {}
            for index, addresses in grouped.items():
                sheet = _sheet(book, index)
                path = by_name.get(sheet.title)
                if not path or not path.startswith("xl/"):
                    raise HTTPException(422, "工作表部件无法定位")
                root = xml_root(archive.read(path))
                _patch_sheet(root, sheet, addresses.values())
                replacements[path] = xml_bytes(root)
            calc = workbook.find(S + "calcPr")
            if calc is not None:
                calc.set("fullCalcOnLoad", "1")
                calc.set("forceFullCalc", "1")
                replacements[WORKBOOK] = xml_bytes(workbook)
            chains = [node for node in relations if node.get("Type", "").endswith("/calcChain")]
            removed = {_part(node.get("Target")) for node in chains}
            if removed:
                for node in chains:
                    relations.remove(node)
                types = xml_root(archive.read("[Content_Types].xml"))
                for node in list(types):
                    if node.get("PartName", "").lstrip("/") in removed:
                        types.remove(node)
                replacements[WORKBOOK_RELS] = xml_bytes(relations)
                replacements["[Content_Types].xml"] = xml_bytes(types)
        return rewrite_package(content, replacements, removed)
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError, etree.XMLSyntaxError) as exc:
        raise HTTPException(422, "工作表结构或单元格内容无法保存") from exc
    finally:
        book.close()
