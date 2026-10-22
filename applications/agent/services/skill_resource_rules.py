"""新表单统一入口的资源约定；旧合同仍由生成器校验。"""
from pathlib import PurePosixPath
import unicodedata

from applications.agent.services.skill_package_builder import safe_relative_path

SCRIPT_SUFFIXES = {".py", ".js", ".sh", ".bash", ".ps1"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
ARCHIVE_SUFFIXES = {".zip", ".whl", ".gz", ".tgz", ".tar"}
REFERENCE_SUFFIXES = {".md", ".txt", ".json", ".csv", ".pdf", ".doc", ".docx", ".xls", ".xlsx"}
ALLOWED_SUFFIXES = SCRIPT_SUFFIXES | IMAGE_SUFFIXES | ARCHIVE_SUFFIXES | REFERENCE_SUFFIXES


def resource_role(filename: str) -> str:
    if "/" in filename or "\\" in filename:
        raise ValueError("上传文件名不能包含目录路径")
    safe_relative_path(filename)
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("不支持此文件类型；请上传脚本、依赖归档、文档或 PNG/JPG/JPEG/GIF/WebP/SVG 图片")
    if suffix in SCRIPT_SUFFIXES:
        return "script"
    return "asset" if suffix in IMAGE_SUFFIXES | ARCHIVE_SUFFIXES else "reference"


def resource_name_key(filename: str) -> str:
    return unicodedata.normalize("NFKC", filename).lower()
