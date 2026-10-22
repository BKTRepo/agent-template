# -*- coding: utf-8 -*-
"""LLM API封装 - 支持OpenAI兼容格式"""

import json
from typing import AsyncIterator, List, Dict, Any

import httpx

from configure import PROJECT_CONFIG


def _supports_thinking_mode(model: str) -> bool:
    name = (model or "").strip().lower()
    return name.startswith("deepseek-v4") or name in {"deepseek-chat", "deepseek-reasoner"}


def _apply_thinking_params(payload: Dict[str, Any], model: str, enable_thinking: bool) -> None:
    """DeepSeek V4 默认开启思考，关闭时需显式传 disabled。"""
    if not _supports_thinking_mode(model):
        return
    if enable_thinking:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = "high"
    else:
        payload["thinking"] = {"type": "disabled"}


def parse_usage_from_chunk(chunk: dict) -> Dict[str, int] | None:
    """从流式或非流式响应 chunk 中解析 token 用量"""
    usage = chunk.get("usage")
    if not usage:
        return None
    details = usage.get("completion_tokens_details") or {}
    reasoning = details.get("reasoning_tokens") or 0
    return {
        "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
        "completion_tokens": usage.get("completion_tokens", 0) or 0,
        "reasoning_tokens": reasoning or 0,
    }


class OpenAICompatibleLLM:
    """OpenAI 兼容 Chat Completions API 客户端（DeepSeek、硅基流动等）"""

    def __init__(self, model: str = None, api_key: str = None, base_url: str = None):
        self.model = model or PROJECT_CONFIG.LLM_MODEL_NAME
        self.api_key = api_key if api_key is not None else PROJECT_CONFIG.LLM_API_KEY
        self.base_url = base_url if base_url is not None else PROJECT_CONFIG.LLM_BASE_URL

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(
            self,
            messages: List[Dict[str, str]],
            temperature: float = 0.7,
            max_tokens: int = 2048,
            top_p: float = 0.95,
            enable_thinking: bool = False,
    ) -> str:
        """
        非流式对话

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大token数
            top_p: top-p采样

        Returns:
            模型回复文本
        """
        if not self.api_key:
            raise ValueError("LLM_API_KEY 未设置")

        import requests

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }
        _apply_thinking_params(payload, self.model, enable_thinking)

        resp = requests.post(
            self.base_url,
            headers=self._get_headers(),
            json=payload,
            timeout=60,
        )

        if resp.status_code != 200:
            raise Exception(f"LLM API调用失败: {resp.text}")

        return resp.json()["choices"][0]["message"]["content"]

    async def stream_chat(
            self,
            messages: List[Dict[str, str]],
            temperature: float = 0.7,
            max_tokens: int = 2048,
            top_p: float = 0.95,
            enable_thinking: bool = False,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        流式对话

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            top_p: top-p采样

        Yields:
            {"type": "content", "content": "..."} 或
            {"type": "usage", "prompt_tokens": N, "completion_tokens": N, "reasoning_tokens": N}
        """
        if not self.api_key:
            raise ValueError("LLM_API_KEY 未设置")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        _apply_thinking_params(payload, self.model, enable_thinking)

        async with httpx.AsyncClient() as client:
            async with client.stream(
                    "POST",
                    self.base_url,
                    headers=self._get_headers(),
                    json=payload,
                    timeout=60,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise Exception(f"流式调用失败: {error_text}")

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0].get("delta", {})
                            reasoning = delta.get("reasoning_content", "")
                            if reasoning:
                                yield {"type": "reasoning", "content": reasoning}
                            content = delta.get("content", "")
                            if content:
                                yield {"type": "content", "content": content}
                            usage = parse_usage_from_chunk(chunk)
                            if usage:
                                yield {"type": "usage", **usage}
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            pass


def format_messages(
        system_prompt: str,
        user_question: str,
        context: str,
        chat_history: List[Dict[str, str]] = None,
        max_history_rounds: int = 10,
        format_context: bool = True,
) -> List[Dict[str, str]]:
    """
    格式化消息列表

    Args:
        system_prompt: 系统提示词模板或已解析内容
        user_question: 用户问题
        context: 检索到的上下文
        chat_history: 历史对话
        max_history_rounds: 保留历史对话轮数
        format_context: 是否将 context 注入 system_prompt 的 {context} 占位符

    Returns:
        格式化后的消息列表
    """
    messages = []

    # 系统消息
    if format_context and "{context}" in system_prompt:
        system_content = system_prompt.format(context=context)
    else:
        system_content = system_prompt
    messages.append({"role": "system", "content": system_content})

    # 历史对话
    if chat_history and max_history_rounds > 0:
        history_limit = max_history_rounds * 2
        for msg in chat_history[-history_limit:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    # 用户当前问题
    messages.append({"role": "user", "content": user_question})

    return messages
