"""DOCX preview and paragraph edits, including paragraphs inside body tables."""

from io import BytesIO
import re

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from fastapi import HTTPException
from pydantic import BaseModel, Field

from .artifact_ooxml import check_package, rewrite_package

MAX_PARAGRAPHS = 2000
PLAIN_RUN_TAGS = {qn(f"w:{tag}") for tag in ("rPr", "t", "tab", "cr", "br")}
PLAIN_PARAGRAPH_TAGS = {qn("w:pPr"), qn("w:r")}
INVALID_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ParagraphEdit(BaseModel):
    id: str = Field(pattern=r"^p[0-9]+$")
    text: str = Field(max_length=32767)


def _editable(paragraph):
    return all(child.tag in PLAIN_PARAGRAPH_TAGS for child in paragraph._p) and all(
        child.tag in PLAIN_RUN_TAGS and (child.tag != qn("w:br") or not child.get(qn("w:type")))
        for run in paragraph.runs for child in run._r
    )


def read_document(content: bytes):
    check_package(content)
    try:
        document = Document(BytesIO(content))
    except Exception as exc:
        raise HTTPException(422, "DOCX 无法读取") from exc
    paragraphs = {}
    cells = {}

    def blocks(container):
        result = []
        for block in container.iter_inner_content():
            if isinstance(block, Paragraph):
                key = f"p{len(paragraphs)}"
                if len(paragraphs) >= MAX_PARAGRAPHS:
                    raise HTTPException(413, "DOCX 段落超过在线处理上限")
                paragraphs[key] = block
                style = block.style.name if block.style else ""
                heading = re.fullmatch(r"Heading ([1-9])", style)
                segments = [
                    {"text": run.text, "bold": bool(run.bold), "italic": bool(run.italic), "underline": bool(run.underline)}
                    for run in block.runs if run.text
                ]
                result.append({
                    "type": "paragraph", "id": key, "text": block.text,
                    "runs": segments if "".join(run["text"] for run in segments) == block.text else [],
                    "heading": int(heading[1]) if heading else 0, "editable": _editable(block),
                })
            else:
                rows = []
                for row in block.rows:
                    cells_in_row = []
                    for cell in row.cells:
                        if cell._tc not in cells:
                            cells[cell._tc] = blocks(cell)
                        cells_in_row.append(cells[cell._tc])
                    rows.append(cells_in_row)
                result.append({"type": "table", "rows": rows})
        return result

    return document, paragraphs, blocks(document)


def _replace_paragraph(paragraph, text):
    old = paragraph.text
    if old == text:
        return
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    # Keep runs outside the edited span unchanged. New text inherits the first edited run.
    start = 0
    while start < min(len(old), len(text)) and old[start] == text[start]:
        start += 1
    end = 0
    while end < min(len(old), len(text)) - start and old[-end - 1] == text[-end - 1]:
        end += 1
    old_end = len(old) - end
    replacement = text[start:len(text) - end]
    offset = 0
    inserted = False
    for run in runs:
        value = run.text
        next_offset = offset + len(value)
        if (next_offset > start and offset < old_end) or (start == old_end and offset <= start <= next_offset and not inserted):
            left = value[:max(0, start - offset)]
            right = value[max(0, old_end - offset):]
            run.text = left + (replacement if not inserted else "") + right
            inserted = True
        offset = next_offset
    if not inserted:
        runs[-1].text += replacement


def save_document(content: bytes, edits: list[ParagraphEdit]) -> bytes:
    document, paragraphs, _ = read_document(content)
    seen = set()
    for edit in edits:
        paragraph = paragraphs.get(edit.id)
        if paragraph is None or edit.id in seen or not _editable(paragraph) or INVALID_TEXT.search(edit.text):
            raise HTTPException(422, "段落已失效或含有不可编辑内容")
        seen.add(edit.id)
        _replace_paragraph(paragraph, edit.text.replace("\r\n", "\n").replace("\r", "\n"))
    part_name = str(document.part.partname).lstrip("/")
    return rewrite_package(content, {part_name: document.part.blob})
