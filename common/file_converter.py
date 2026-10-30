# -*- coding: utf-8 -*-
"""
@Author  : zhoushengjie
@Project : KeenRobot
@Module  : file_converter.py
@DateTime: 2026/6/11

使用 docling 将办公文档（DOCX、PPTX、XLSX、HTML、PDF）转换为 Markdown。
支持离线模式：当 docling_offline 目录存在时，使用本地模型缓存；
否则使用 docling 默认配置（联网下载模型）。
"""
import os
import sys
from pathlib import Path
from typing import Optional

from configure import LOGGER, PROJECT_CONFIG

SUPPORTED_EXTS = {".docx", ".pptx", ".xlsx", ".html", ".htm", ".pdf"}

# 延迟初始化：首次调用时才构建 Converter
_CONVERTER = None


def _init_converter():
    """初始化 DocumentConverter，根据 cache 目录是否存在决定离线/在线模式。"""
    global _CONVERTER
    if _CONVERTER is not None:
        return _CONVERTER

    offline_dir = Path(PROJECT_CONFIG.DOCLING_OFFLINE_DIR)
    use_offline = offline_dir.is_dir()

    if use_offline:
        LOGGER.info(f"[file_converter] 检测到离线模型目录，启用离线模式: {offline_dir}")
        # 设置离线环境变量
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"

        models_dir = offline_dir / "docling" / "models"
        rapid_ocr_dir = offline_dir / "rapidocr"
        hf_cache_dir = offline_dir / "huggingface"
        os.environ["HF_HOME"] = str(hf_cache_dir)

        from docling.datamodel.base_models import InputFormat  # noqa: E402
        from docling.datamodel.pipeline_options import (  # noqa: E402
            PdfPipelineOptions,
            RapidOcrOptions,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption  # noqa: E402

        # 构建 RapidOCR 选项（通过构造函数传入模型路径）
        rapid_ocr_kwargs = {}
        if rapid_ocr_dir.is_dir():
            rapid_ocr_kwargs["det_model_path"] = str(
                rapid_ocr_dir / "ch_PP-OCRv4_det_mobile.onnx"
            )
            rapid_ocr_kwargs["cls_model_path"] = str(
                rapid_ocr_dir / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"
            )
            rapid_ocr_kwargs["rec_model_path"] = str(
                rapid_ocr_dir / "ch_PP-OCRv4_rec_mobile.onnx"
            )
            rapid_ocr_kwargs["rec_keys_path"] = str(
                rapid_ocr_dir / "ppocr_keys_v1.txt"
            )
        rapid_ocr_opts = RapidOcrOptions(**rapid_ocr_kwargs)

        # 构建 PDF 流水线选项（artifacts_path 传给 PdfPipelineOptions）
        pipeline_kwargs = {
            "do_ocr": True,
            "ocr_options": rapid_ocr_opts,
        }
        if models_dir.is_dir():
            pipeline_kwargs["artifacts_path"] = str(models_dir)
        else:
            LOGGER.warning(f"[file_converter] 未找到 docling 模型缓存 {models_dir}")

        pdf_pipeline_options = PdfPipelineOptions(**pipeline_kwargs)

        _CONVERTER = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_pipeline_options),
            }
        )
    else:
        LOGGER.info("[file_converter] 未检测到离线模型目录，使用 docling 默认在线模式")
        from docling.document_converter import DocumentConverter  # noqa: E402
        _CONVERTER = DocumentConverter()

    return _CONVERTER


def convert_file_to_md(input_path: str | Path, output_path: Optional[str | Path] = None) -> Path:
    """将单个文件转换为 Markdown。

    Args:
        input_path: 输入文件路径。
        output_path: 输出文件路径，默认为同名 .md 文件。

    Returns:
        生成的 Markdown 文件路径。

    Raises:
        FileNotFoundError: 输入文件不存在。
        ValueError: 不支持的文件类型。
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"文件不存在: {input_path}")

    ext = input_path.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(
            f"不支持的文件类型: {ext}。"
            f"支持的格式: {', '.join(sorted(SUPPORTED_EXTS))}"
        )

    converter = _init_converter()
    result = converter.convert(str(input_path))
    markdown = result.document.export_to_markdown()

    if output_path is None:
        output_path = input_path.with_suffix(".md")
    else:
        output_path = Path(output_path)

    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def convert_dir_to_md(
    input_dir: str | Path,
    output_dir: Optional[str | Path] = None,
    recursive: bool = False,
) -> list[tuple[Path, Path]]:
    """批量转换目录下所有支持格式的文件为 Markdown。

    Args:
        input_dir: 输入目录路径。
        output_dir: 输出目录路径，默认与输入目录相同。
        recursive: 是否递归处理子目录。

    Returns:
        转换结果列表，每个元素为 (输入路径, 输出路径)。
    """
    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise NotADirectoryError(f"目录不存在: {input_dir}")

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    pattern = "**/*" if recursive else "*"
    files = [
        p for p in input_dir.glob(pattern)
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    ]

    results = []
    for f in files:
        rel = f.relative_to(input_dir)
        out = (
            output_dir.joinpath(rel).with_suffix(".md")
            if output_dir
            else f.with_suffix(".md")
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            convert_file_to_md(f, out)
            results.append((f, out))
            LOGGER.info(f"[file_converter] 转换成功: {f} -> {out}")
        except Exception as exc:
            LOGGER.exception(f"[file_converter] 转换失败: {f}: {exc}")
            results.append((f, None))

    return results
