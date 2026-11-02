# -*- coding: utf-8 -*-
from typing import List

from dataclasses import dataclass, field
from pathlib import Path
import shutil
import subprocess
import tempfile


@dataclass
class LangchainDocument:
    """只保留旧 loader 使用的 page_content/metadata 接口，避免加载时启动模型依赖。"""
    page_content: str
    metadata: dict = field(default_factory=dict)


def load_document_pages(file_path: str, file_type: str) -> List[LangchainDocument]:
    """
    按文件类型加载文档页面列表。

    :param file_path: 文件绝对/相对路径
    :param file_type: 文件类型标识（pdf/txt/docx）
    :return: LangChain Document 列表
    """
    path = Path(file_path)
    if file_type in {"txt", "md"}:
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return [LangchainDocument(page_content=raw.decode(encoding))]
            except UnicodeDecodeError:
                pass
        raise ValueError("文本编码无法识别，请使用 UTF-8")
    if file_type == "pdf":
        import fitz
        with fitz.open(path) as pdf:
            if pdf.needs_pass:
                raise ValueError("PDF 已加密，请先提供可读取的文档")
            return [LangchainDocument(page_content=page.get_text(), metadata={"page": i})
                    for i, page in enumerate(pdf)]
    if file_type == "docx":
        from docx import Document
        doc = Document(path)
        # 按 XML 原始顺序读取段落与表格，避免把全部表格移到文末。
        lines = []
        for node in doc.element.body:
            if node.tag.endswith("}p"):
                text = "".join(node.xpath(".//w:t/text()"))
                styles = node.xpath("./w:pPr/w:pStyle/@w:val")
                style = styles[0] if styles else ""
                heading = style.lower().replace("heading", "")
                prefix = "#" * int(heading) + " " if heading.isdigit() and 1 <= int(heading) <= 6 else ""
                lines.append(prefix + text)
            elif node.tag.endswith("}tbl"):
                for row in node.xpath("./w:tr"):
                    cells = [" ".join(cell.xpath(".//w:t/text()")) for cell in row.xpath("./w:tc")]
                    lines.append(" | ".join(cells))
        return [LangchainDocument(page_content="\n\n".join(lines))]
    if file_type == "xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            return [LangchainDocument(page_content=f"# {sheet.title}\n\n" + "\n".join(
                " | ".join("" if cell is None else str(cell) for cell in row)
                for row in sheet.iter_rows(values_only=True)), metadata={"sheet": sheet.title}) for sheet in book]
        finally:
            book.close()
    if file_type == "xls":
        import xlrd
        book = xlrd.open_workbook(path, on_demand=True)
        try:
            return [LangchainDocument(page_content=f"# {sheet.name}\n\n" + "\n".join(
                " | ".join(str(value) for value in sheet.row_values(i)) for i in range(sheet.nrows))) for sheet in book.sheets()]
        finally:
            book.release_resources()
    if file_type == "doc":
        binary = shutil.which("soffice") or shutil.which("libreoffice")
        if not binary:
            raise ValueError("解析旧版 .doc 需要服务器安装 LibreOffice；也可另存为 .docx 后上传")
        with tempfile.TemporaryDirectory(prefix="knowledge-doc-") as temp:
            profile = (Path(temp) / "profile").as_uri()
            subprocess.run([binary, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "docx",
                            "--outdir", temp, str(path.resolve())], check=True, capture_output=True, timeout=180)
            converted = Path(temp) / (path.stem + ".docx")
            return load_document_pages(str(converted), "docx")
    raise ValueError(f"不支持的知识库文件类型: {file_type}")
