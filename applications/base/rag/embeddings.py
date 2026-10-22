# -*- coding: utf-8 -*-
"""Embedding API封装 - OpenAI 兼容格式（硅基流动、DashScope 兼容模式等）"""

from typing import List, Tuple

import requests

from configure import PROJECT_CONFIG

# DashScope 常见误配：/api/v1 并非 OpenAI 兼容 embeddings 路径
DASHSCOPE_COMPATIBLE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def is_embedding_configured() -> bool:
    """是否已配置 Embedding API Key"""
    return bool(_resolve_api_key())


def _resolve_api_key() -> str:
    return (PROJECT_CONFIG.EMBEDDING_API_KEY or "").strip()


def _normalize_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def _resolve_embedding_api(base_url: str) -> Tuple[str, str]:
    """
    解析 Embedding 请求地址与协议模式。

    Returns:
        (url, mode) — mode 为 openai 或 dashscope_native
    """
    base = _normalize_base_url(base_url)

    if "dashscope" in base.lower():
        if "compatible-mode" in base:
            url = base if base.endswith("/embeddings") else f"{base}/embeddings"
            return url, "openai"
        if "/services/embeddings" in base:
            return base, "dashscope_native"
        # 误配为 /api/v1 时自动切到兼容模式，避免 BadRequest.IllegalInput
        if base.endswith("/api/v1"):
            return f"{DASHSCOPE_COMPATIBLE_BASE}/embeddings", "openai"

    url = base if base.endswith("/embeddings") else f"{base}/embeddings"
    return url, "openai"


def _build_payload(model: str, texts: List[str], mode: str) -> dict:
    if mode == "dashscope_native":
        return {"model": model, "input": {"texts": texts}}
    return {"model": model, "input": texts, "encoding_format": "float"}


def _parse_embeddings(result: dict, mode: str) -> List[List[float]]:
    if mode == "dashscope_native":
        output = result.get("output") or {}
        items = output.get("embeddings") or []
        return [item["embedding"] for item in items]

    data = result.get("data") or []
    return [item["embedding"] for item in data]


def get_embedding(texts: List[str], model: str = None) -> List[List[float]]:
    """
    调用 Embedding API 获取文本向量

    Args:
        texts: 文本列表
        model: 模型名称，默认使用配置中的模型

    Returns:
        向量列表
    """
    api_key = _resolve_api_key()
    if not api_key:
        raise ValueError("EMBEDDING_API_KEY 未设置，请在 .env 中配置 Embedding API Key")

    model = model or PROJECT_CONFIG.EMBEDDING_MODEL_NAME
    sanitized = [t for t in texts if t and str(t).strip()]
    if not sanitized:
        return []

    batch_size = 10
    all_embeddings: List[List[float]] = []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url, mode = _resolve_embedding_api(PROJECT_CONFIG.EMBEDDING_BASE_URL)

    for i in range(0, len(sanitized), batch_size):
        batch = sanitized[i: i + batch_size]
        payload = _build_payload(model, batch, mode)

        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=60,
        )

        if resp.status_code != 200:
            raise Exception(
                f"Embedding API调用失败: {resp.text} "
                f"(url={url}, model={model}, mode={mode})"
            )

        result = resp.json()
        embeddings = _parse_embeddings(result, mode)
        if len(embeddings) != len(batch):
            raise Exception(
                f"Embedding API 返回数量不匹配: 期望 {len(batch)}，实际 {len(embeddings)}"
            )
        all_embeddings.extend(embeddings)

    return all_embeddings


def get_single_embedding(text: str, model: str = None) -> List[float]:
    """获取单条文本的向量"""
    if not text or not str(text).strip():
        raise ValueError("无法为空文本生成向量")
    embeddings = get_embedding([text], model)
    return embeddings[0]
