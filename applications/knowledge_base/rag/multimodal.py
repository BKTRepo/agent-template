# -*- coding: utf-8 -*-
"""多模态分析——读取 sidecar 文件并回写 VLM 结果。

实现移植自 LightRAG：读取 ``drawings.json`` / ``tables.json``，
对每个条目调用 VLM，并将 ``llm_analyze_result`` 回写到文件中。
"""

import json
import time as _time
from pathlib import Path
from typing import Any, Dict, List

from applications.knowledge_base.rag.table_rows import is_toc_table, parse_html_table
from configure import PROJECT_CONFIG


class MultimodalStageIncompleteError(RuntimeError):
    """多模态条目未全部成功；整个多模态步骤必须重试。"""


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def analyze_multimodal(
    drawings_path: str,
    tables_path: str,
    artifacts_dir: str,
    *,
    enable_vlm: bool = PROJECT_CONFIG.ENABLE_VLM,
) -> Dict[str, Any]:
    """读取 sidecar 文件，逐个分析图片 / 表格，并将结果回写。

    :param drawings_path: ``drawings.json`` 的路径。
    :param tables_path: ``tables.json`` 的路径。
    :param artifacts_dir: ``artifacts/`` 目录路径（用于解析图片 URI）。
    :param enable_vlm: 为 True 且 VLM 已配置时，调用 VLM API。
    :return: 摘要字典（与 LightRAG 的 analyze_multimodal 返回结构一致）。
    """
    drawings_raw = _read_json(drawings_path)
    tables_raw = _read_json(tables_path)

    # LightRAG 约定：sidecar JSON 带有 "version" 以及 "drawings"/"tables" 键
    drawings = drawings_raw if isinstance(drawings_raw, list) else (
        drawings_raw.get("drawings", {}) if isinstance(drawings_raw, dict) else {}
    )
    tables = tables_raw if (isinstance(tables_raw, dict) and not tables_raw.get("version")) else (
        tables_raw.get("tables", {}) if isinstance(tables_raw, dict) else {}
    )

    if not drawings and not tables:
        return {"analyzing_stage_skipped": True, "multimodal_processed": False}

    vlm_available = enable_vlm and PROJECT_CONFIG.VLM_API_BASE and PROJECT_CONFIG.VLM_MODEL
    processed = False
    drawings_changed = False
    tables_changed = False

    # 分析图片
    drawings_dict = drawings if isinstance(drawings, dict) else {}
    if not drawings_dict and isinstance(drawings, list):
        # 兜底：将 list 转换为 dict
        drawings_dict = {str(i): e for i, e in enumerate(drawings) if isinstance(e, dict)}
    for did, entry in drawings_dict.items():
        if not isinstance(entry, dict):
            continue
        if vlm_available:
            _analyze_drawing_vlm(entry, artifacts_dir)
        else:
            _analyze_drawing_meta(entry)
        processed = True
        drawings_changed = True

    # 分析表格
    tables_dict = tables if isinstance(tables, dict) else {}
    for tid, entry in tables_dict.items():
        if not isinstance(entry, dict):
            continue
        # 跳过目录表（新 sidecar 已在生成端剔除, 此处兜底旧产物, 避免浪费 VLM 调用）
        if is_toc_table(parse_html_table(entry.get("body", ""))):
            continue
        if vlm_available:
            _analyze_table_vlm(tid, entry)
        else:
            _analyze_table_meta(tid, entry)
        processed = True
        tables_changed = True

    failures = []
    failures.extend(
        f"图片 {did}: {entry.get('llm_analyze_result', {}).get('message', '未知错误')}"
        for did, entry in drawings_dict.items()
        if isinstance(entry, dict)
        and entry.get("llm_analyze_result", {}).get("status") == "failed"
    )
    failures.extend(
        f"表格 {tid}: {entry.get('llm_analyze_result', {}).get('message', '未知错误')}"
        for tid, entry in tables_dict.items()
        if isinstance(entry, dict)
        and entry.get("llm_analyze_result", {}).get("status") == "failed"
    )
    if failures:
        # 不回写任何 sidecar：一个条目失败即视为整个步骤失败，下次重试
        # 从相同解析输入完整执行多模态步骤，不混用不同轮次的条目结果。
        preview = "; ".join(failures[:3])
        raise MultimodalStageIncompleteError(
            f"多模态分析未完成：{len(failures)} 个条目失败；{preview}"
        )

    # 所有条目成功后才一次性提交 sidecar 产物。
    if drawings_changed:
        _write_json(drawings_path, {"version": "1.0", "drawings": drawings_dict})
    if tables_changed:
        _write_json(tables_path, {"version": "1.0", "tables": tables_dict})

    return {
        "multimodal_processed": processed,
        "analyzing_stage_skipped": not processed,
        "image_descriptions": [
            _drawing_chunk_data(e) for e in drawings_dict.values()
            if isinstance(e, dict) and "llm_analyze_result" in e
        ],
        "table_summaries": [
            _table_chunk_data(tid, e) for tid, e in tables_dict.items()
            if isinstance(e, dict) and "llm_analyze_result" in e
        ],
    }


def build_multimodal_chunks(
    mm_result: Dict[str, Any],
    text_chunks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """将多模态块追加到文本块之后。"""
    combined = list(text_chunks)
    order = len(combined)
    for img in mm_result.get("image_descriptions", []):
        combined.append({"content": img.get("content", ""), "tokens": img.get("tokens", 0),
                         "chunk_order_index": order, "modality": "image"})
        order += 1
    for tbl in mm_result.get("table_summaries", []):
        combined.append({"content": tbl.get("content", ""), "tokens": tbl.get("tokens", 0),
                         "chunk_order_index": order, "modality": "table"})
        order += 1
    return combined


# ---------------------------------------------------------------------------
# VLM 分析（读取真实图片文件）
# ---------------------------------------------------------------------------

def _analyze_drawing_vlm(entry: Dict[str, Any], artifacts_dir: str) -> None:
    try:
        # 延迟导入：仅在实际执行 VLM 分析时才加载 vlm 模块（及其 httpx 依赖）
        from applications.knowledge_base.rag.vlm import describe_image
        path = entry.get("path", "")
        full_path = str(Path(artifacts_dir) / Path(path).name) if path else ""
        if full_path and Path(full_path).exists():
            desc = describe_image(full_path)
        else:
            desc = _metadata_description(entry)
        entry["llm_analyze_result"] = {
            "name": entry.get("captions", [""])[0] or f"图片 {entry.get('id', '')}",
            "type": "Image",
            "description": desc,
            "analyze_time": int(_time.time()),
            "status": "success",
        }
    except Exception as exc:
        entry["llm_analyze_result"] = {
            "name": "", "type": "Image", "description": "",
            "analyze_time": int(_time.time()), "status": "failed",
            "message": str(exc),
        }


def _analyze_table_vlm(tid: str, entry: Dict[str, Any]) -> None:
    try:
        # 延迟导入：仅在实际执行 VLM 分析时才加载 vlm 模块（及其 httpx 依赖）
        from applications.knowledge_base.rag.vlm import describe_table
        body = entry.get("body", "")
        # 将 HTML 表格解析为二维列表，供 VLM 调用使用
        rows = parse_html_table(body)
        caption = (entry.get("captions") or [""])[0]
        desc = describe_table(rows, caption)
        entry["llm_analyze_result"] = {
            "name": caption or tid,
            "description": desc,
            "analyze_time": int(_time.time()),
            "status": "success",
        }
    except Exception as exc:
        entry["llm_analyze_result"] = {
            "name": "", "description": "",
            "analyze_time": int(_time.time()), "status": "failed",
            "message": str(exc),
        }


# ---------------------------------------------------------------------------
# 元数据兜底分析（不使用 VLM）
# ---------------------------------------------------------------------------

def _analyze_drawing_meta(entry: Dict[str, Any]) -> None:
    entry["llm_analyze_result"] = {
        "name": (entry.get("captions") or [""])[0] or f"{entry.get('id', '')}",
        "type": "Image",
        "description": _metadata_description(entry),
        "analyze_time": int(_time.time()),
        "status": "success",
    }


def _analyze_table_meta(tid: str, entry: Dict[str, Any]) -> None:
    rows = entry.get("num_rows", 0)
    cols = entry.get("num_cols", 0)
    caption = (entry.get("captions") or [""])[0]
    parts = [f"[表格]"]
    if caption:
        parts.append(f"标题: {caption}")
    parts.append(f"大小: {rows} 行 × {cols} 列")
    entry["llm_analyze_result"] = {
        "name": caption or tid,
        "description": " | ".join(parts),
        "analyze_time": int(_time.time()),
        "status": "success",
    }


# ---------------------------------------------------------------------------
# 块内容构建
# ---------------------------------------------------------------------------

def _drawing_chunk_data(entry: Dict[str, Any]) -> Dict[str, Any]:
    r = entry.get("llm_analyze_result", {})
    name = r.get("name", "")
    typ = r.get("type", "")
    desc = r.get("description", "")
    content = f"[图片] {name}\n类型: {typ}\n\n{desc}"
    return {"content": content, "tokens": max(1, len(content) // 2), **entry}


def _table_chunk_data(tid: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    r = entry.get("llm_analyze_result", {})
    name = r.get("name", "")
    desc = r.get("description", "")
    content = f"[表格] {name}\n\n{desc}"
    return {"content": content, "tokens": max(1, len(content) // 2), "id": tid, **entry}


def _metadata_description(entry: Dict[str, Any]) -> str:
    parts = []
    w, h = entry.get("width"), entry.get("height")
    if w and h:
        parts.append(f"尺寸: {w}×{h}")
    captions = entry.get("captions") or []
    ctext = " ".join(c for c in captions if c)
    if ctext:
        parts.append(f"标题: {ctext}")
    mime = entry.get("mimetype", "")
    if mime:
        parts.append(f"类型: {mime}")
    return " | ".join(parts) if parts else "图片"


# ---------------------------------------------------------------------------
# JSON 辅助函数
# ---------------------------------------------------------------------------

def _read_json(path: Any) -> Any:
    # sidecar 某一类不存在时调用方可能传空字符串/空列表；Path("") 会
    # 解析为当前目录，若只检查 exists() 随后会把目录当文件打开。
    if not isinstance(path, (str, Path)) or not str(path).strip():
        return None
    p = Path(path)
    if not p.is_file():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: Any) -> None:
    target = Path(path)
    temporary = target.with_name(f".{target.name}.tmp")
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temporary.replace(target)
