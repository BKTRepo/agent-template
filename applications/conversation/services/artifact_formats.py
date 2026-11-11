"""Content adapters for ordinary assistant artifacts."""

from codecs import BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE
from hashlib import sha256
from io import BytesIO
import json
import re

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font

from applications.conversation.exceptions import ConversationBusinessError
from .artifact_documents import read_document
from .artifact_spreadsheet import sheet_metadata

MAX_TEXT_LENGTH = 2 * 1024 * 1024
TEXT_SAMPLES = {
    "py": 'def validate_account(name: str) -> bool:\n    return bool(name.strip())\n',
    "js": 'export const validateAccount = name => Boolean(name.trim());\n',
    "ts": 'export const validateAccount = (name: string): boolean => Boolean(name.trim());\n',
    "sh": '#!/usr/bin/env sh\nprintf "%s\\n" "checking account settings"\n',
    "sql": 'SELECT account_id, status FROM test_accounts WHERE status = \'active\';\n',
    "md": '# 开户测试说明\n\n- 校验必填项\n- 覆盖证件有效期边界\n',
    "json": '{\n  "scenario": "信用卡开户",\n  "enabled": true,\n  "limit": 100\n}\n',
}


def _decode(content):
    for bom, encoding in ((BOM_UTF8, "utf-8"), (BOM_UTF16_LE, "utf-16-le"), (BOM_UTF16_BE, "utf-16-be")):
        if content.startswith(bom):
            try:
                return content[len(bom):].decode(encoding), encoding, bom
            except UnicodeDecodeError as exc:
                raise ConversationBusinessError("文本编码无效") from exc
    for encoding in ("utf-8", "gb18030"):
        try:
            return content.decode(encoding), encoding, b""
        except UnicodeDecodeError:
            continue
    raise ConversationBusinessError("文本编码无法识别")


def _text(content):
    text, encoding, bom = _decode(content)
    if len(text) > MAX_TEXT_LENGTH:
        raise ConversationBusinessError("文本超过在线编辑上限")
    if "\x00" in text:
        raise ConversationBusinessError("文件包含二进制内容，无法在线编辑")
    return text, encoding, bom


def _invalid_json_constant(value):
    raise ValueError(value)


def save_text(content: bytes, text: str, file_type: str) -> bytes:
    original, encoding, bom = _text(content)
    if len(text) > MAX_TEXT_LENGTH or "\x00" in text:
        raise ConversationBusinessError("文本包含无效字符或超过编辑上限")
    if file_type == "json":
        try:
            json.loads(text, parse_constant=_invalid_json_constant)
        except (ValueError, RecursionError) as exc:
            raise ConversationBusinessError("JSON 格式有误，请检查后再保存") from exc
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized == original.replace("\r\n", "\n").replace("\r", "\n"):
        return content
    original_line_end = re.search(r"\r\n|\n|\r", original)
    line_end = original_line_end[0] if original_line_end else "\n"
    try:
        return bom + normalized.replace("\n", line_end).encode(encoding)
    except UnicodeEncodeError as exc:
        raise ConversationBusinessError("修改内容无法用原文件编码保存") from exc


def ordinary_detail(artifact, content):
    result = {
        "artifact_id": artifact.id, "name": artifact.name, "file_type": artifact.file_type,
        "is_test_case": False, "base_hash": sha256(content).hexdigest(),
    }
    if artifact.file_type == "docx":
        return {**result, "editor": "word", "blocks": read_document(content)[2]}
    if artifact.file_type == "xlsx":
        return {**result, "editor": "sheet", "sheets": sheet_metadata(content)}
    text, encoding, _ = _text(content)
    return {**result, "editor": "text", "text": text, "encoding": encoding}


def make_demo_file(kind):
    if kind in TEXT_SAMPLES:
        return TEXT_SAMPLES[kind].encode("utf-8")
    stream = BytesIO()
    if kind == "docx":
        document = Document()
        document.add_heading("信用卡开户测试报告", level=1)
        paragraph = document.add_paragraph()
        paragraph.add_run("测试范围").bold = True
        paragraph.add_run("覆盖开户资料、身份验证与证件边界。")
        table = document.add_table(rows=2, cols=2)
        table.style = "Table Grid"
        for row, values in zip(table.rows, (("测试项", "结果"), ("开户资料校验", "通过"))):
            for cell, value in zip(row.cells, values):
                cell.text = value
        document.add_paragraph("本次回归结论为通过。")
        document.save(stream)
    else:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "开户测试数据"
        sheet.append(("场景", "额度", "有效", "校验公式"))
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.append(("正常开户", 100, True, "=B2*2"))
        sheet.append(("限额边界", 200, False, "=B3*2"))
        workbook.create_sheet("字段说明").append(("额度为测试环境合成数据",))
        workbook.save(stream)
    return stream.getvalue()
