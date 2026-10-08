import asyncio
import os
from pathlib import Path
from uuid import uuid4

from ..models import MarkdownDocument


def document_directory():
    default = Path(__file__).resolve().parents[3] / 'output' / 'docs' / 'strategy_trimmer'
    return Path(os.environ.get('TRIMMER_DOCUMENT_DIR', str(default))).resolve()


def document_path(record: MarkdownDocument):
    directory = document_directory()
    path = (directory / record.file_key).resolve()
    if path.parent != directory or not path.is_file():
        return None
    return path


def metadata(record: MarkdownDocument):
    return {'documentId': record.document_id, 'reqId': record.requirement_id,
            'name': record.requirement_name, 'filename': record.filename,
            'downloadUrl': record.download_url, 'createdAt': record.created_at.isoformat(),
            'configVersion': record.config_version}


async def save_document(request, filename: str, markdown: str, version: str):
    directory = document_directory()
    directory.mkdir(parents=True, exist_ok=True)
    document_id = uuid4().hex
    file_key = document_id + '.md'
    file_path = directory / file_key
    temporary = file_path.with_suffix('.tmp')
    def write():
        temporary.write_text(markdown, encoding='utf-8', newline='\n')
        temporary.replace(file_path)
    try:
        await asyncio.to_thread(write)
        return await MarkdownDocument.create(document_id=document_id, requirement_id=request.reqId,
            requirement_name=request.name, filename=filename, file_key=file_key,
            download_url=f'/strategy-trimmer/documents/{document_id}/download', config_version=version)
    except Exception:
        temporary.unlink(missing_ok=True)
        file_path.unlink(missing_ok=True)
        raise


async def find_latest(requirement_id: str | None, name: str | None):
    requirement_id = (requirement_id or '').strip()
    name = (name or '').strip()
    if not requirement_id and not name:
        raise ValueError('请至少填写需求编号或需求名称')
    query = MarkdownDocument.all()
    if requirement_id:
        query = query.filter(requirement_id=requirement_id)
    if name:
        query = query.filter(requirement_name=name)
    return await query.order_by('-created_at', '-id').first()
