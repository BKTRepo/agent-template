"""Markdown原文只放受控文件；SQL只存相对路径。"""
import hashlib
import os
from pathlib import Path
import uuid
from configure import PROJECT_CONFIG


def root_path():
    return Path(PROJECT_CONFIG.SKILL_BUILD_DIR).resolve()


def controlled_path(relative):
    from applications.wrq.agent.services.developer_skill_crud import DeveloperError
    if not relative or Path(relative).is_absolute() or '\\' in relative:
        raise DeveloperError('Skill定义路径无效', 409)
    path = (root_path() / relative).resolve()
    if not path.is_relative_to(root_path()):
        raise DeveloperError('Skill定义路径越界', 409)
    return path


def write_markdown(skill_id, text):
    prefix = hashlib.sha256(str(skill_id).encode()).hexdigest()[:24]
    relative = f'definitions/{prefix}/{uuid.uuid4().hex}.md'
    path = controlled_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix('.tmp')
    try:
        with staged.open('xb') as stream:
            stream.write(text.encode('utf8'))
            stream.flush()
            os.fsync(stream.fileno())
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)
    return relative


def read_markdown(relative):
    from applications.wrq.agent.services.developer_skill_crud import DeveloperError
    if not relative:
        return ''
    path = controlled_path(relative)
    if not path.is_file():
        raise DeveloperError('Skill定义原文件缺失，请检查文件存储', 409)
    if path.stat().st_size > 2_000_000:
        raise DeveloperError('Skill定义原文件超过读取限制', 409)
    try:
        return path.read_bytes().decode('utf8')
    except UnicodeDecodeError as exc:
        raise DeveloperError('Skill定义原文件不是UTF-8文本', 409) from exc


def discard_markdown(relative):
    if relative:
        controlled_path(relative).unlink(missing_ok=True)
