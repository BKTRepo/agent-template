"""Local MarkItDown conversion; no plugins, cloud clients or PDF splitting."""
import asyncio
import io
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from zipfile import ZipFile, BadZipFile

SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.xlsx', '.md', '.txt'}


class ConversionCancelledError(RuntimeError):
    pass


def validate_document(data: bytes, filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError('仅支持 PDF、DOCX、XLSX、MD、TXT 文件')
    if not data:
        raise ValueError('文件内容为空')
    if suffix == '.pdf' and b'%PDF-' not in data[:1024]:
        raise ValueError('不是有效的 PDF 文件')
    if suffix in {'.docx', '.xlsx'}:
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                required = 'word/document.xml' if suffix == '.docx' else 'xl/workbook.xml'
                if '[Content_Types].xml' not in archive.namelist() or required not in archive.namelist():
                    raise ValueError('Office 文件格式与后缀不匹配')
        except BadZipFile as exc:
            raise ValueError('Office 文件损坏或受密码保护') from exc


def _convert(data: bytes, filename: str, directory: str) -> str:
    from markitdown import MarkItDown, StreamInfo
    validate_document(data, filename)
    result = MarkItDown(enable_plugins=False).convert_stream(
        io.BytesIO(data), stream_info=StreamInfo(extension=Path(filename).suffix.lower()),
    )
    markdown = result.text_content
    if not markdown or not markdown.strip():
        raise ValueError('未提取到可入库文字；基础 MarkItDown 不提供扫描 PDF 或截图 OCR')
    path = Path(directory) / (Path(filename).stem + '.md')
    path.write_text(markdown, encoding='utf-8')
    return markdown


async def convert_document_to_bundle(data, filename, job_id, *, should_cancel=None, **_):
    from applications.knowledge_base.processing.docling_bundle import BundleResult
    from configure import PROJECT_CONFIG
    directory = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR) / job_id
    directory.mkdir(parents=True, exist_ok=True)
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'))
    task = asyncio.get_running_loop().run_in_executor(pool, _convert, data, filename, str(directory))
    try:
        while not task.done():
            if should_cancel and should_cancel():
                raise ConversionCancelledError('任务已取消')
            await asyncio.wait({task}, timeout=1)
        markdown = task.result()
        return BundleResult(bundle_dir=directory, md_path=directory / (Path(filename).stem + '.md'), markdown=markdown)
    finally:
        # A cancelled conversion must not leave an orphan process writing artifacts.
        for process in list((getattr(pool, '_processes', None) or {}).values()):
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        pool.shutdown(wait=False, cancel_futures=True)
