#!/usr/bin/env python3
"""
使用 docling 将办公文档（DOCX、PPTX、XLSX、HTML、PDF）转换为 Markdown。

用法示例：
    # 单文件转换（输出同名 .md 文件）
    python3 convert_to_md.py document.docx

    # 指定输出路径
    python3 convert_to_md.py document.docx -o output.md

    # 批量转换目录下所有文件
    python3 convert_to_md.py ./documents/

    # 递归处理子目录
    python3 convert_to_md.py ./documents/ -r -o ./markdown_output/

说明：
    - 脚本使用 ./docling_offline/ 作为所有离线模型的根目录。
    - PDF 的 OCR 使用 RapidOCR，加载本地 ONNX 模型。
    - 建议 Python 3.10+。
"""

import os
import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 离线环境：禁止所有外部网络请求
# ---------------------------------------------------------------------------
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

# ---------------------------------------------------------------------------
# 路径相对于本脚本解析（无论从哪里运行都能正确定位）
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR / "docling_offline"
MODELS_DIR = CACHE_DIR / "docling" / "models"
RAPID_OCR_DIR = CACHE_DIR / "rapidocr"
HF_CACHE_DIR = CACHE_DIR / "huggingface"

# 将 HuggingFace 缓存指向本地目录
os.environ["HF_HOME"] = str(HF_CACHE_DIR)

# ---------------------------------------------------------------------------
# 配置 docling 使用本地模型
# ---------------------------------------------------------------------------
from docling.datamodel.settings import settings  # noqa: E402

if MODELS_DIR.is_dir():
    settings.artifacts_path = MODELS_DIR
else:
    print(f"警告：未找到 docling 模型缓存 {MODELS_DIR}", file=sys.stderr)
    print("  请运行：docling-tools models download", file=sys.stderr)

# ---------------------------------------------------------------------------
# 配置 PDF 流水线：启用 RapidOCR（本地模型）
# ---------------------------------------------------------------------------
from docling.datamodel.base_models import InputFormat  # noqa: E402
from docling.datamodel.pipeline_options import (  # noqa: E402
    PdfPipelineOptions,
    RapidOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption  # noqa: E402

rapid_ocr_opts = RapidOcrOptions()

# 如果本地 RapidOCR 模型存在，则指向本地路径
if RAPID_OCR_DIR.is_dir():
    rapid_ocr_opts.det_model_path = str(RAPID_OCR_DIR / "ch_PP-OCRv4_det_mobile.onnx")
    rapid_ocr_opts.cls_model_path = str(
        RAPID_OCR_DIR / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"
    )
    rapid_ocr_opts.rec_model_path = str(
        RAPID_OCR_DIR / "ch_PP-OCRv4_rec_mobile.onnx"
    )
    rapid_ocr_opts.rec_keys_path = str(RAPID_OCR_DIR / "ppocr_keys_v1.txt")

pdf_pipeline_options = PdfPipelineOptions()
pdf_pipeline_options.do_ocr = True
pdf_pipeline_options.ocr_options = rapid_ocr_opts

CONVERTER = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_pipeline_options),
    }
)

SUPPORTED_EXTS = {".docx", ".pptx", ".xlsx", ".html", ".htm", ".pdf"}


def convert_file(input_path: Path, output_path: Path | None = None) -> Path:
    """将单个文件转换为 Markdown。"""
    if not input_path.exists():
        raise FileNotFoundError(f"文件不存在: {input_path}")

    ext = input_path.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(
            f"不支持的文件类型: {ext}。"
            f"支持的格式: {', '.join(sorted(SUPPORTED_EXTS))}"
        )

    result = CONVERTER.convert(str(input_path))
    markdown = result.document.export_to_markdown()

    if output_path is None:
        output_path = input_path.with_suffix(".md")

    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="使用 docling 将 DOCX/PPTX/XLSX/HTML/PDF 文件转换为 Markdown。"
    )
    parser.add_argument("input", help="输入文件路径或目录")
    parser.add_argument(
        "-o",
        "--output",
        help="输出文件或目录（默认：同名 .md 文件）",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="递归处理子目录",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else None

    if input_path.is_dir():
        if output_path is not None and not output_path.is_dir():
            print("错误：输入为目录时，输出也必须为目录。")
            return 1

        pattern = "**/*" if args.recursive else "*"
        files = [
            p
            for p in input_path.glob(pattern)
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        ]
        if not files:
            print(f"未找到支持的文件: {input_path}")
            return 0

        for f in files:
            rel = f.relative_to(input_path)
            out = (
                output_path.joinpath(rel).with_suffix(".md")
                if output_path
                else f.with_suffix(".md")
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                convert_file(f, out)
                print(f"OK  {f} -> {out}")
            except Exception as e:
                print(f"ERR {f}: {e}")
    else:
        try:
            out = convert_file(input_path, output_path)
            print(f"OK  {input_path} -> {out}")
        except Exception as e:
            print(f"ERR {input_path}: {e}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
