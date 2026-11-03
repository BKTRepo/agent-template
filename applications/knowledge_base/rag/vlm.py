# -*- coding: utf-8 -*-
"""VLM（视觉语言模型）客户端——OpenAI 兼容 API。

支持 Ollama、OpenAI 或任意 OpenAI 兼容的视觉服务端点。
"""

import base64
from pathlib import Path
from typing import Any, Dict, List

import httpx

from configure import PROJECT_CONFIG

# 图片描述提示词（业务数据，保持原文）
_IMAGE_PROMPT = """Please describe this image in detail. Include:
1. What type of image it is (photo, chart, diagram, screenshot, etc.)
2. The main content and key elements
3. Any text visible in the image
4. The likely purpose or context of this image in a document

Respond in the same language as the image content. Keep the description concise (2-4 sentences)."""

# 表格分析提示词（业务数据，保持原文）
_TABLE_PROMPT = """Please analyze this table and describe:
1. What the table is about
2. The key columns and their meanings
3. Any notable patterns or important data points

Respond in the same language as the table content. Keep it concise (2-4 sentences)."""


def _encode_image(image_path: str) -> str:
    """读取图片文件并返回 base64 data URI。"""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")
    ext = path.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def describe_image(image_path: str) -> str:
    """将图片发送给 VLM 并返回其描述。"""
    data_uri = _encode_image(image_path)

    payload: Dict[str, Any] = {
        "model": PROJECT_CONFIG.VLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _IMAGE_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
        "max_tokens": 300,
        "temperature": 0.2,
    }

    headers = {"Content-Type": "application/json"}
    if PROJECT_CONFIG.VLM_API_KEY and PROJECT_CONFIG.VLM_API_KEY != "not-needed":
        headers["Authorization"] = f"Bearer {PROJECT_CONFIG.VLM_API_KEY}"

    # 同步调用（保持原有行为，不改为异步）
    resp = httpx.post(
        f"{PROJECT_CONFIG.VLM_API_BASE}/chat/completions",
        json=payload,
        headers=headers,
        timeout=httpx.Timeout(60.0),
        verify=False,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def describe_table(table_data: List[List[str]], caption: str = "") -> str:
    """将表格发送给 LLM 并返回摘要。"""
    rows_text = "\n".join(" | ".join(str(c) for c in row) for row in table_data[:10])
    user_text = f"Table caption: {caption or '(none)'}\n\nTable data:\n{rows_text}"

    payload: Dict[str, Any] = {
        "model": PROJECT_CONFIG.VLM_MODEL,
        "messages": [{"role": "user", "content": _TABLE_PROMPT + "\n\n" + user_text}],
        "max_tokens": 200,
        "temperature": 0.2,
    }

    headers = {"Content-Type": "application/json"}
    if PROJECT_CONFIG.VLM_API_KEY and PROJECT_CONFIG.VLM_API_KEY != "not-needed":
        headers["Authorization"] = f"Bearer {PROJECT_CONFIG.VLM_API_KEY}"

    # 同步调用（保持原有行为，不改为异步）
    resp = httpx.post(
        f"{PROJECT_CONFIG.VLM_API_BASE}/chat/completions",
        json=payload,
        headers=headers,
        timeout=httpx.Timeout(30.0),
        verify=False,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()
