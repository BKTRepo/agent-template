# -*- coding: utf-8 -*-
"""LLM 客户端 — OpenAI 兼容的 Chat Completions 调用, 实现移植自 LightRAG (tenacity 重试, 支持流式与非流式)。"""

from typing import Any, AsyncIterator, Dict, List, Optional, Union

from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from configure import PROJECT_CONFIG


def _provider_temperature(value: Any) -> float:
    """Kimi Coding 端点只接受 temperature=1，其他 OpenAI 兼容端点保留原值。"""
    if "api.kimi.com/coding" in PROJECT_CONFIG.LLM_BASE_URL.lower():
        return 1.0
    return float(value)


class LLMTruncatedError(RuntimeError):
    """LLM 输出因触及 max_tokens 上限被截断（finish_reason == "length"）。

    对结构化输出（JSON 模式）而言截断必然导致解析失败, 原样重试同一请求
    只会得到同样的截断——故该异常不参与 tenacity 重试, 由调用方决定降级
    策略（如术语提取侧对半重切批次后重试）。
    """
    def __init__(self, message: str, *, partial: str = "", finish_reason: str = "length"):
        super().__init__(message)
        self.partial = partial or ""
        self.finish_reason = finish_reason


class LLMTokenStream:
    """兼容原 async iterator，同时保留流式 finish_reason/partial 状态。"""

    def __init__(self, response: Any):
        self._iterator = response.__aiter__()
        self.finish_reason: Optional[str] = None
        self.error: Optional[BaseException] = None
        self.partial = ""

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        while True:
            try:
                chunk = await self._iterator.__anext__()
            except StopAsyncIteration:
                raise
            except BaseException as exc:
                self.error = exc
                raise
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            reason = getattr(choice, "finish_reason", None)
            if reason:
                self.finish_reason = reason
            delta = getattr(choice, "delta", None)
            token = getattr(delta, "content", None) if delta is not None else None
            if token:
                self.partial += token
                return token


def _create_llm_client() -> Any:
    """创建指向所配置 LLM 服务地址的 AsyncOpenAI 客户端。"""
    # 延迟导入: 避免在模块加载时引入 openai 重依赖
    from openai import AsyncOpenAI

    api_key = PROJECT_CONFIG.LLM_API_KEY
    api_key = api_key if (api_key and api_key != "not-needed") else "none"
    return AsyncOpenAI(base_url=PROJECT_CONFIG.LLM_BASE_URL, api_key=api_key)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    # 截断异常不重试: 同请求重试必然再次截断, 重试只白白消耗指数退避等待
    retry=retry_if_not_exception_type(LLMTruncatedError),
    reraise=True,
)
async def _chat_completion_inner(
        messages: List[Dict[str, str]],
        stream: bool = False,
        **kwargs: Any,
) -> Union[str, AsyncIterator[str]]:
    """带重试的核心补全调用。

    :param messages: 完整消息列表 (system + 历史 + user)。
    :param stream: 是否流式返回。
    :return: 非流式返回完整响应字符串; 流式返回逐 token 的异步生成器。
    """
    client = _create_llm_client()
    params: Dict[str, Any] = {
        "model": PROJECT_CONFIG.LLM_MODEL,
        "messages": messages,
        "max_tokens": PROJECT_CONFIG.LLM_MAX_TOKENS,
        "temperature": _provider_temperature(PROJECT_CONFIG.LLM_TEMPERATURE),
        "stream": stream,
        **kwargs,
    }

    response = await client.chat.completions.create(**params)

    if not stream:
        choice = response.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            # 输出被 max_tokens 截断: 结构化输出场景下结果必然不完整,
            # 抛专门异常让调用方走降级路径（而非当作普通失败静默丢弃）
            partial = getattr(getattr(choice, "message", None), "content", "") or ""
            raise LLMTruncatedError(
                f"LLM 输出被截断（finish_reason=length, "
                f"max_tokens={params.get('max_tokens')}）",
                partial=partial,
            )
        content = choice.message.content
        return content if content else ""

    # 流式模式: 返回逐 token 输出的异步生成器
    return LLMTokenStream(response)


async def chat_completion(
        messages: Union[str, List[Dict[str, str]]],
        system_prompt: Optional[str] = None,
        history_messages: Optional[List[Dict[str, str]]] = None,
        conversation_summary: Optional[str] = None,
        conversation_recall: Optional[str] = None,
        stream: bool = False,
        enable_cot: bool = False,
        response_format: Optional[Dict[str, str]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
) -> Union[str, AsyncIterator[str]]:
    """高层对话补全接口, 与 LightRAG 的调用模式保持一致。

    :param messages: 用户消息字符串或消息字典列表。
    :param system_prompt: 可选的系统级指令。
    :param history_messages: 历史对话轮次 ``[{"role": "user/assistant", "content": "..."}]``。
    :param conversation_summary: 可选的对话滚动摘要（早期轮次压缩）, 三模式统一前置并入 system。
    :param conversation_recall: 可选的 L4 向量回忆（召回的旧轮次 Q/A）, 前置并入 system。
    :param stream: 是否逐 token 流式返回。
    :param enable_cot: 为 True 时在系统提示词中追加思维链引导。
    :param response_format: 可选的结构化输出格式, 如 ``{"type": "json_object"}``。
    :param model: 可选的模型名, 覆盖 LLM_MODEL 默认配置（如前端指定的模型）。
    :return: 非流式: 完整响应字符串; 流式: 逐 token 输出的异步生成器。
    """
    # 构建完整消息列表
    api_messages: List[Dict[str, str]] = []

    # 记忆上下文（滚动摘要 + L4 向量回忆）统一前置并入 system（三模式一致）
    summary_block = ""
    if conversation_summary:
        summary_block += f"---对话背景摘要---\n{conversation_summary}\n\n"
    if conversation_recall:
        summary_block += (
            f"---相关历史对话（从本会话较早轮次召回, 供参考）---\n"
            f"{conversation_recall}\n\n"
        )
    if system_prompt or summary_block:
        sys_content = summary_block + (system_prompt or "")
        if enable_cot:
            # 追加思维链引导 (与中文系统提示词保持一致);
            # 推理过程要求内部完成、不外显, 避免流式输出时把推理痕迹直接吐给用户
            cot_hint = (
                "\n\n---推理要求---\n"
                "回答前请先内部完成以下推理（不要输出推理过程，只输出最终答案）：\n"
                "1. 明确用户问题的核心诉求；\n"
                "2. 从参考资料中筛选出与该诉求直接相关的分块，忽略无关分块；\n"
                "3. 若相关信息分散在多个分块，先组织逻辑顺序再作答；\n"
                "4. 检查答案是否每个要点都能在参考资料中找到依据。"
            )
            if cot_hint not in sys_content:
                sys_content += cot_hint
        api_messages.append({"role": "system", "content": sys_content})

    # 注入历史对话
    if history_messages:
        for msg in history_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                api_messages.append({"role": role, "content": content})

    # 添加当前用户消息
    if isinstance(messages, str):
        api_messages.append({"role": "user", "content": messages})
    else:
        api_messages.extend(messages)

    kwargs: Dict[str, Any] = {}
    if response_format:
        kwargs["response_format"] = response_format
    if temperature is not None:
        kwargs["temperature"] = _provider_temperature(temperature)
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if model:
        # 覆盖 _chat_completion_inner 内的默认 LLM_MODEL
        kwargs["model"] = model

    result = await _chat_completion_inner(api_messages, stream=stream, **kwargs)

    # 防御性处理: 非流式请求若拿到的不是字符串, 则将流式生成器聚合为完整字符串
    if not stream and not isinstance(result, str):
        collected: List[str] = []
        async for token in result:
            collected.append(token)
        return "".join(collected)

    return result
