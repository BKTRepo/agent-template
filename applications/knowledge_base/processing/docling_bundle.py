# -*- coding: utf-8 -*-
"""docling 转换产物包 —— 统一的解析结果数据结构。

每个文档的转换产物统一落在 ``RAG_OUTPUT_DIR/<job_id>/`` 目录下:
- ``<文件名主干>.md``: Markdown 全文
- ``<文件名主干>.json``: DoclingDocument 结构化 JSON（侧车文件与合并流程消费）
- ``artifacts/``: 图片等媒体产物（可选）
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class BundleResult:
    """文档转换产物包。"""

    bundle_dir: Path
    json_path: Optional[Path] = None
    md_path: Optional[Path] = None
    artifacts_dir: Optional[Path] = None
    markdown: str = ""
    docling_document: Dict[str, Any] = field(default_factory=dict)

    def as_response_dict(self, filename: str, task_id: str) -> dict:
        return {
            "filename": filename,
            "task_id": task_id,
            "bundle_dir": str(self.bundle_dir.resolve()),
            "json_path": str(self.json_path.resolve()) if self.json_path else None,
            "md_path": str(self.md_path.resolve()) if self.md_path else None,
            "artifacts_dir": str(self.artifacts_dir.resolve()) if self.artifacts_dir else None,
            "markdown": self.markdown,
        }
