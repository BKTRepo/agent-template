"""Count current file content, so edits and archived copies cannot leave stale counters."""
from io import BytesIO
from zipfile import ZipFile

from openpyxl import load_workbook

from applications.conversation.exceptions import ConversationBusinessError, TestCaseWorkbookFormatError
from .artifact_mock import read_original, file_write_lock
from .artifact_workbook import read_workbook, MAX_EXPANDED_BYTES


def file_quantity(path, class_id):
    if path.suffix.lower() != '.xlsx':
        return 1, '份'
    with file_write_lock(path):
        content = read_original(path)
    if class_id != 3:
        try:
            book, cases, _, _ = read_workbook(content)
            book.close()
            return len(cases), '条'
        except TestCaseWorkbookFormatError:
            return 1, '份'
    with ZipFile(BytesIO(content)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED_BYTES:
            raise ConversationBusinessError('测试数据解压后超过统计上限')
    book = load_workbook(BytesIO(content), read_only=True, data_only=False)
    try:
        count = 0
        for sheet in book.worksheets:
            rows = sheet.iter_rows(values_only=True)
            # Each data sheet has one header row. Blank/whitespace-only rows do not count.
            next(rows, None)
            count += sum(1 for row in rows if any(value is not None and str(value).strip() for value in row))
        return count, '条'
    finally:
        book.close()


def content_quantity(files, class_id, resolve):
    totals = {}
    for file in files:
        count, unit = file_quantity(resolve(file.storage_key), class_id)
        totals[unit] = totals.get(unit, 0) + count
    return '、'.join(f'{count}{unit}' for unit, count in totals.items()) or '0份'
