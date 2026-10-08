import asyncio
from io import BytesIO
from zipfile import BadZipFile, ZipFile
from xml.etree.ElementTree import ParseError

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from tortoise.transactions import in_transaction

from ..models import SystemAutomationAsset

HEADERS = ('系统名称', '接口/UI自动化')
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10000


def parse_asset_workbook(content: bytes):
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('请选择非空且不超过 2 MB 的 .xlsx 文件')
    try:
        with ZipFile(BytesIO(content)) as archive:
            if len(archive.infolist()) > 200 or sum(item.file_size for item in archive.infolist()) > 20 * 1024 * 1024:
                raise ValueError('Excel 解压后内容过大，请使用提供的两列模板')
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=False)
    except (BadZipFile, KeyError, OSError, SyntaxError, InvalidFileException, ParseError, ValueError) as exc:
        raise ValueError('无法解析文件，请上传有效的 .xlsx 模板') from exc
    try:
        if '系统自动化资产' not in workbook.sheetnames:
            raise ValueError('模板缺少“系统自动化资产”工作表')
        sheet = workbook['系统自动化资产']
        if (sheet.max_row or 0) > MAX_ROWS + 1 or (sheet.max_column or 0) > 2:
            raise ValueError('模板只允许两列、最多 10000 条对应关系')
        # Read real rows instead of trusting XLSX dimension metadata or silently truncating extra columns.
        sheet.reset_dimensions()
        rows = sheet.iter_rows(max_col=3)
        header = next(rows, ())
        if tuple(cell.value for cell in header[:2]) != HEADERS or (len(header) > 2 and header[2].value is not None):
            raise ValueError('首行必须为“系统名称”“接口/UI自动化”')
        result = {}
        seen = set()
        for row_number, cells in enumerate(rows, 2):
            if row_number > MAX_ROWS + 1:
                raise ValueError('模板最多允许 10000 条对应关系')
            if cells[2].value is not None:
                raise ValueError(f'第 {row_number} 行超出模板的两列范围')
            name, status = (cell.value for cell in cells[:2])
            if name is None and status is None:
                continue
            if any(cell.data_type == 'f' for cell in cells):
                raise ValueError(f'第 {row_number} 行不能使用公式，请填写实际值')
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
                raise ValueError(f'第 {row_number} 行系统名称不能为空且不能超过 100 字')
            name = name.strip()
            if name.casefold() in seen:
                raise ValueError(f'第 {row_number} 行系统名称重复：{name}')
            seen.add(name.casefold())
            if status not in ('有自动化资产', '无自动化资产'):
                raise ValueError(f'第 {row_number} 行只能填写“有自动化资产”或“无自动化资产”')
            result[name] = status == '有自动化资产'
        if not result:
            raise ValueError('Excel 没有可导入的系统关系')
        return result
    finally:
        workbook.close()


async def import_assets(content: bytes):
    parsed = await asyncio.to_thread(parse_asset_workbook, content)
    created = updated = 0
    async with in_transaction() as connection:
        for name, has_asset in parsed.items():
            _, was_created = await SystemAutomationAsset.update_or_create(
                system_name=name, defaults={'has_automation': has_asset}, using_db=connection)
            created += int(was_created)
            updated += int(not was_created)
    return {'total': len(parsed), 'created': created, 'updated': updated}
