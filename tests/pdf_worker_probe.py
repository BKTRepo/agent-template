"""源 RAG 测试替身：跨 spawn 子进程可导入，不需要实际 OCR 模型。"""
import os
import time
from pathlib import Path


def blocking_chunk(chunk, do_ocr, force_ocr, output_root, cancel_event):
    Path(output_root, f"worker-{os.getpid()}.pid").write_text(str(os.getpid()))
    time.sleep(60)
    return []


def blocking_loader(path, file_type, connection):
    Path(path).write_text(str(os.getpid()))
    time.sleep(60)


def successful_chunk(chunk, do_ocr, force_ocr, output_root, cancel_event):
    from common.docling_bundle import BundleResult
    idx, filename, _, bundle_name = chunk[0]
    root = Path(output_root, bundle_name)
    bundle = BundleResult(bundle_dir=root, json_path=root / "a.json", md_path=root / "a.md",
        artifacts_dir=None, markdown=filename, docling_document={})
    return [(idx, bundle, None, None)]
