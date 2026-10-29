"""新表单统一入口的资源约定；旧合同仍由生成器校验。"""
from pathlib import PurePosixPath
import unicodedata

from applications.wrq.agent.services.skill_package_builder import safe_relative_path

SCRIPT_SUFFIXES = {".py", ".js"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
ARCHIVE_SUFFIXES = set()
REFERENCE_SUFFIXES = {".md", ".xlsx", ".docx"}
ALLOWED_SUFFIXES = SCRIPT_SUFFIXES | IMAGE_SUFFIXES | REFERENCE_SUFFIXES


def resource_role(filename: str) -> str:
    if "/" in filename or "\\" in filename:
        raise ValueError("上传文件名不能包含目录路径")
    safe_relative_path(filename)
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("支持 .py/.js/.md/.xlsx/.docx/.png/.jpg/.jpeg")
    if suffix in SCRIPT_SUFFIXES:
        return "script"
    return "asset" if suffix in IMAGE_SUFFIXES | ARCHIVE_SUFFIXES else "reference"


def resource_name_key(filename: str) -> str:
    return unicodedata.normalize("NFKC", filename).lower()
