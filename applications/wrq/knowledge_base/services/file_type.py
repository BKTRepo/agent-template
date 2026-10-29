# -*- coding: utf-8 -*-
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class FileTypeConfig:
    """文件类型配置"""

    extensions: Tuple[str, ...]
    label: str
    loader_enabled: bool


FILE_TYPE_REGISTRY: Dict[str, FileTypeConfig] = {
    "pdf": FileTypeConfig(extensions=(".pdf",), label="PDF", loader_enabled=True),
    "txt": FileTypeConfig(extensions=(".txt",), label="纯文本", loader_enabled=True),
    "md": FileTypeConfig(extensions=(".md",), label="Markdown", loader_enabled=True),
    "docx": FileTypeConfig(extensions=(".docx",), label="Word文档", loader_enabled=True),
    "doc": FileTypeConfig(extensions=(".doc",), label="旧版Word", loader_enabled=True),
    "xlsx": FileTypeConfig(extensions=(".xlsx",), label="Excel", loader_enabled=True),
    "xls": FileTypeConfig(extensions=(".xls",), label="旧版Excel", loader_enabled=True),
}


def detect_file_type(filename: str) -> Optional[str]:
    """根据文件名扩展名识别文件类型"""
    if not filename:
        return None
    lower_name = filename.lower()
    for file_type, config in FILE_TYPE_REGISTRY.items():
        if lower_name.endswith(config.extensions):
            return file_type
    return None


def get_accept_extensions() -> List[str]:
    """获取前端上传组件可接受的扩展名列表"""
    extensions: List[str] = []
    for config in FILE_TYPE_REGISTRY.values():
        extensions.extend(config.extensions)
    return extensions


def get_supported_type_labels() -> str:
    """获取支持格式的可读描述（用于提示文案）"""
    labels = [config.label for config in FILE_TYPE_REGISTRY.values()]
    return "、".join(labels)


def validate_file_type(filename: str) -> str:
    """
    校验文件类型是否受支持且 loader 已启用。

    :return: 文件类型标识（如 pdf）
    :raises ValueError: 格式未知或 loader 未实现
    """
    file_type = detect_file_type(filename)
    if not file_type:
        supported = ", ".join(get_accept_extensions())
        raise ValueError(f"不支持的文件格式，当前支持: {supported}")

    config = FILE_TYPE_REGISTRY[file_type]
    if not config.loader_enabled:
        raise ValueError(f"{config.label} 格式暂未开放解析，请稍后或使用 PDF 文件")

    return file_type
