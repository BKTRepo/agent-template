"""Original-file previews, independent of ingestion; callers must authorize every read."""
import asyncio
from datetime import date, datetime, time
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

import httpx
from filelock import FileLock, Timeout
from configure import PROJECT_CONFIG
from .platform_service import KnowledgeError


def original_path(doc, generation=None):
    if generation is not None and doc.generation != generation:
        raise KnowledgeError('文件已更新，请重新打开预览', 'generation', 409)
    path = Path(doc.file_path).resolve()
    if not path.is_relative_to(PROJECT_CONFIG.upload_path.resolve()) or not path.is_file():
        raise KnowledgeError('原文件不存在', status_code=404)
    return path


def fingerprint(doc):
    path = original_path(doc)
    stat = path.stat()
    return (str(path), doc.generation, doc.content_hash or '', stat.st_size, stat.st_mtime_ns)


def _book(path):
    from openpyxl import load_workbook
    try:
        with zipfile.ZipFile(path) as archive:
            expanded = sum(item.file_size for item in archive.infolist())
        if expanded > 128 * 1024 * 1024:
            raise KnowledgeError('工作簿解压后较大，请下载原文件查看', 'preview', 413)
        return load_workbook(path, read_only=expanded > 16 * 1024 * 1024, data_only=False, keep_links=False)
    except KnowledgeError:
        raise
    except Exception as exc:
        raise KnowledgeError('工作簿无法预览，文件可能损坏或受密码保护', 'preview', 422) from exc


@lru_cache(maxsize=16)
def workbook_metadata(key):
    book = _book(key[0])
    try:
        return [{'index': i, 'name': sheet.title, 'rows': sheet.max_row or 0, 'columns': sheet.max_column or 0}
                for i, sheet in enumerate(book.worksheets) if sheet.sheet_state == 'visible']
    finally:
        book.close()


def _color(value):
    return '#' + value.rgb[-6:] if value and value.type == 'rgb' and isinstance(value.rgb, str) else None


@lru_cache(maxsize=32)
def workbook_page(key, sheet_index, offset, limit, column_offset, column_limit):
    from openpyxl.utils import get_column_letter
    book = _book(key[0])
    try:
        if sheet_index >= len(book.worksheets) or book.worksheets[sheet_index].sheet_state != 'visible':
            raise KnowledgeError('工作表不存在', 'sheet_index', 404)
        sheet = book.worksheets[sheet_index]
        row_count, column_count = sheet.max_row or 0, sheet.max_column or 0
        cells = []
        if offset < row_count and column_offset < column_count:
            for row in sheet.iter_rows(min_row=offset + 1, max_row=min(offset + limit, row_count),
                                       min_col=column_offset + 1, max_col=min(column_offset + column_limit, column_count)):
                values = []
                for cell in row:
                    value = cell.value
                    if isinstance(value, (datetime, date, time)):
                        value = value.isoformat()
                    elif value is not None and not isinstance(value, (str, int, float, bool)):
                        value = str(value)
                    font, fill, alignment = cell.font, cell.fill, cell.alignment
                    values.append({'value': value, 'formula': cell.data_type == 'f', 'bold': bool(font and font.bold),
                        'color': _color(font.color) if font else None,
                        'background': _color(fill.fgColor) if fill and fill.patternType == 'solid' else None,
                        'align': alignment.horizontal if alignment and alignment.horizontal in {'left', 'center', 'right'} else None})
                cells.append(values)
        merges = [[area.min_row, area.min_col, area.max_row, area.max_col] for area in getattr(sheet, 'merged_cells', [])
                  if area.max_row > offset and area.min_row <= offset + limit and area.max_col > column_offset and area.min_col <= column_offset + column_limit]
        return {'sheet_index': sheet_index, 'name': sheet.title, 'total_rows': row_count, 'total_columns': column_count,
            'offset': offset, 'column_offset': column_offset, 'limit': limit,
            'columns': [get_column_letter(i) for i in range(column_offset + 1, min(column_offset + column_limit, column_count) + 1)],
            'rows': cells, 'merges': merges, 'streaming': book.read_only, 'formula_note': '公式仅展示表达式，不重新计算。'}
    finally:
        book.close()


async def metadata(doc):
    original_path(doc)
    extension = Path(doc.filename).suffix.lower().lstrip('.')
    viewer = {'pdf': 'pdf', 'docx': 'pdf', 'xlsx': 'spreadsheet', 'md': 'markdown',
              'txt': 'text', 'json': 'text', 'csv': 'text'}.get(extension, 'unsupported')
    return {'format': extension, 'viewer': viewer,
        'sheets': await asyncio.to_thread(workbook_metadata, fingerprint(doc)) if extension == 'xlsx' else []}


async def converted_pdf(doc):
    path = original_path(doc)
    if path.suffix.lower() == '.pdf':
        return path
    if path.suffix.lower() != '.docx':
        raise KnowledgeError('该格式不支持 PDF 预览', 'preview', 400)
    key = hashlib.sha256(json.dumps(fingerprint(doc)).encode()).hexdigest()
    cache = Path(PROJECT_CONFIG.DOCUMENT_PREVIEW_CACHE_DIR).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (key + '.pdf')
    lock = FileLock(str(target) + '.lock', thread_local=False)
    acquired = False
    try:
        for _ in range(300):
            try:
                await asyncio.to_thread(lock.acquire, timeout=0)
                acquired = True
                break
            except Timeout:
                await asyncio.sleep(0.2)
        if not acquired:
            raise KnowledgeError('预览转换繁忙，请稍后重试', 'preview', 503)
        if target.is_file() and target.stat().st_size:
            return target
        url = PROJECT_CONFIG.DOCUMENT_PREVIEW_CONVERTER_URL.rstrip('/')
        if not url:
            raise KnowledgeError('Word 预览服务未配置，请联系管理员或下载原文件查看', 'preview', 503)
        try:
            async with httpx.AsyncClient(timeout=PROJECT_CONFIG.DOCUMENT_PREVIEW_TIMEOUT, trust_env=False) as client:
                with path.open('rb') as stream:
                    response = await client.post(url + '/forms/libreoffice/convert',
                        files={'files': ('document.docx', stream, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
                response.raise_for_status()
            if not response.content.startswith(b'%PDF-'):
                raise ValueError('Invalid converter response')
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=cache, suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(response.content)
                temporary.replace(target)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
            return target
        except (httpx.HTTPError, ValueError) as exc:
            raise KnowledgeError('Word 转 PDF 失败，请稍后重试或下载原文件查看', 'preview', 503) from exc
    finally:
        if acquired:
            await asyncio.to_thread(lock.release)
