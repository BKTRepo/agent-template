"""仅供单次任务使用的临时上传文件。"""
import asyncio
import re
import shutil
import socket
import tempfile
import time
from pathlib import Path

from fastapi import HTTPException
from applications.chat.models.chat_model import ChatTask
from configure import PROJECT_CONFIG

ALLOWED_SUFFIXES = {'.pdf', '.docx', '.xlsx', '.txt', '.md', '.json', '.csv', '.py', '.js', '.sql', '.sh', '.png', '.jpg', '.jpeg'}
MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_TOTAL_SIZE = 100 * 1024 * 1024


def upload_root():
    return Path(PROJECT_CONFIG.OUTPUT_DATAGRAM_DIR).resolve() / 'chat_uploads'


def task_upload_dir(task_id):
    return upload_root() / f'task-{int(task_id)}'


async def save_uploads(files):
    if not files or len(files) > 10:
        raise HTTPException(400, '请选择1至10个附件')
    root = upload_root()
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='staging-', dir=root))
    total = 0
    try:
        for index, file in enumerate(files):
            name = (file.filename or '').replace('\\', '/').split('/')[-1].strip()
            if not name or len(name) > 255 or re.search(r'[\x00-\x1f\x7f]', name) or Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
                raise HTTPException(400, '文件名或文件类型不支持')
            target = directory / str(index) / name
            target.parent.mkdir()
            size = 0
            with target.open('wb') as dst:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    total += len(chunk)
                    if size > MAX_FILE_SIZE or total > MAX_TOTAL_SIZE:
                        raise HTTPException(413, '单个附件不能超过20MB，合计不能超过100MB')
                    dst.write(chunk)
            if not size:
                raise HTTPException(400, '附件不能为空')
        return directory
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        for file in files:
            await file.close()


def remove_task_uploads(task_id):
    path = task_upload_dir(task_id)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)


async def stage_attachments(task, input_dir):
    source_root = task_upload_dir(task.id)
    if not source_root.exists():
        return []
    entries = []
    for folder in sorted(source_root.iterdir()):
        if not folder.is_dir() or folder.is_symlink() or not folder.name.isdecimal():
            raise ValueError('附件目录无效')
        for source in folder.iterdir():
            if not source.is_file() or source.is_symlink():
                raise ValueError('附件文件无效')
            target = input_dir / 'attachments' / folder.name / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copyfile, source, target)
            entries.append({'file_name': source.name, 'path': f'/input/attachments/{folder.name}/{source.name}'})
    return entries


async def cleanup_uploads():
    root = upload_root()
    if not root.is_dir():
        return
    for path in root.iterdir():
        if path.is_symlink() or not path.is_dir():
            continue
        if path.name.startswith('staging-'):
            # 请求被进程中断留下的未提交上传目录。
            if time.time() - path.stat().st_mtime > 86400:
                await asyncio.to_thread(shutil.rmtree, path)
        elif path.name.startswith('task-') and path.name[5:].isdecimal():
            task = await ChatTask.get_or_none(id=int(path.name[5:]))
            # 目录属于当前主机；只有任务结束或数据库记录已消失才清理。
            if (not task and time.time() - path.stat().st_mtime > 3600) or (
                    task and task.worker_host == socket.gethostname() and task.status in ('success', 'failed', 'cancelled')):
                await asyncio.to_thread(shutil.rmtree, path)
