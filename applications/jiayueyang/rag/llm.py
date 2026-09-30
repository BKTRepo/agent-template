# -*- coding: utf-8 -*-
"""LLM 客户端 — OpenAI 兼容的 Chat Completions 调用, 实现移植自 LightRAG (tenacity 重试, 支持流式与非流式)。"""

import asyncio
import json
import time
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from configure import LOGGER, PROJECT_CONFIG


def _now_iso() -> str:
    """Return a local-time timestamp for LLM call records and logs."""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _usage_tuple(usage: Any):
    """Extract (prompt, completion, total) token counts when available."""
    if usage is None:
        return None, None, None
    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        getattr(usage, "total_tokens", None),
    )


def _error_brief(exc: BaseException, limit: int = 2000) -> str:
    return f"{type(exc).__name__}: {exc}"[:limit]


async def _persist_call_record(**kwargs: Any) -> None:
    """Persist observability data without allowing the side channel to break RAG."""
    try:
        from applications.jiayueyang.models.llm_call_log_model import LLMCallLog

        await LLMCallLog.create(**kwargs)
    except Exception as exc:
        LOGGER.warning("LLM 调用记录落库失败(不影响业务): {}", exc)


def _spawn_persist(**kwargs: Any) -> None:
    try:
        asyncio.get_running_loop().create_task(_persist_call_record(**kwargs))
    except RuntimeError:
        LOGGER.warning("LLM 调用记录未落库: 当前无运行中的事件循环")


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

    def __init__(
            self,
            response: Any,
            *,
            model: str,
            prompt_text: str,
            start_at: datetime,
            start_monotonic: float,
    ):
        self._iterator = response.__aiter__()
        self._model = model
        self._prompt_text = prompt_text
        self._start_at = start_at
        self._start_monotonic = start_monotonic
        self._first_token_monotonic: Optional[float] = None
        self._recorded = False
        self.finish_reason: Optional[str] = None
        self.error: Optional[BaseException] = None
        self.partial = ""

    def __aiter__(self):
        return self

    def _record(self, *, success: bool, error_message: Optional[str] = None) -> None:
        if self._recorded:
            return
        self._recorded = True
        total_ms = int((time.monotonic() - self._start_monotonic) * 1000)
        first_token_ms = None
        if self._first_token_monotonic is not None:
            first_token_ms = int((self._first_token_monotonic - self._start_monotonic) * 1000)
        _spawn_persist(
            model=self._model,
            stream=True,
            success=success,
            error_message=error_message,
            start_at=self._start_at,
            end_at=datetime.now().astimezone(),
            total_ms=total_ms,
            first_token_ms=first_token_ms,
            prompt_text=self._prompt_text,
            completion_text=self.partial,
            prompt_chars=len(self._prompt_text),
            completion_chars=len(self.partial),
        )

    async def __anext__(self) -> str:
        while True:
            try:
                chunk = await self._iterator.__anext__()
            except StopAsyncIteration:
                self._record(success=True)
                raise
            except BaseException as exc:
                self.error = exc
                self._record(success=False, error_message=_error_brief(exc))
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
                if self._first_token_monotonic is None:
                    self._first_token_monotonic = time.monotonic()
                self.partial += token
                return token

    async def aclose(self) -> None:
        """记录用户主动停止流式消费，并关闭供应商迭代器。"""
        self._record(success=False, error_message="流式输出提前结束(消费方关闭生成器)")
        close = getattr(self._iterator, "aclose", None)
        if close is not None:
            await close()


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

    llm_start = time.monotonic()
    start_at = datetime.now().astimezone()
    actual_model = params.get("model") or PROJECT_CONFIG.LLM_MODEL
    prompt_text = json.dumps(messages, ensure_ascii=False, default=str)
    LOGGER.info(
        "LLM 请求开始: model={}; start_at={}; stream={}",
        actual_model,
        _now_iso(),
        stream,
    )
    try:
        response = await client.chat.completions.create(**params)
    except Exception as exc:
        _spawn_persist(
            model=actual_model,
            stream=stream,
            success=False,
            error_message=_error_brief(exc),
            start_at=start_at,
            end_at=datetime.now().astimezone(),
            total_ms=int((time.monotonic() - llm_start) * 1000),
            prompt_text=prompt_text,
            prompt_chars=len(prompt_text),
        )
        raise

    if not stream:
        try:
            choice = response.choices[0]
            content = getattr(choice.message, "content", None) or ""
            if getattr(choice, "finish_reason", None) == "length":
                # 输出被 max_tokens 截断: 记录后交给调用方执行精简重生成。
                _spawn_persist(
                    model=actual_model,
                    stream=False,
                    success=False,
                    error_message="LLM 输出被截断(finish_reason=length)",
                    start_at=start_at,
                    end_at=datetime.now().astimezone(),
                    total_ms=int((time.monotonic() - llm_start) * 1000),
                    prompt_text=prompt_text,
                    completion_text=content,
                    prompt_chars=len(prompt_text),
                    completion_chars=len(content),
                )
                raise LLMTruncatedError(
                    f"LLM 输出被截断（finish_reason=length, "
                    f"max_tokens={params.get('max_tokens')}）",
                    partial=content,
                )
            prompt_tokens, completion_tokens, total_tokens = _usage_tuple(
                getattr(response, "usage", None)
            )
            total_ms = int((time.monotonic() - llm_start) * 1000)
            LOGGER.info(
                "LLM 完整响应结束: model={}; start_at={}; end_at={}; 耗时={} ms; Token 用量: 输入={}, 输出={}, 总计={}",
                actual_model,
                start_at.isoformat(timespec="milliseconds"),
                _now_iso(),
                total_ms,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
            _spawn_persist(
                model=actual_model,
                stream=False,
                success=True,
                start_at=start_at,
                end_at=datetime.now().astimezone(),
                total_ms=total_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                prompt_text=prompt_text,
                completion_text=content,
                prompt_chars=len(prompt_text),
                completion_chars=len(content),
            )
            return content
        except LLMTruncatedError:
            raise
        except Exception as exc:
            _spawn_persist(
                model=actual_model,
                stream=False,
                success=False,
                error_message=_error_brief(exc),
                start_at=start_at,
                end_at=datetime.now().astimezone(),
                total_ms=int((time.monotonic() - llm_start) * 1000),
                prompt_text=prompt_text,
                prompt_chars=len(prompt_text),
            )
            raise

    # 流式模式: 返回逐 token 输出的异步生成器
    return LLMTokenStream(
        response,
        model=actual_model,
        prompt_text=prompt_text,
        start_at=start_at,
        start_monotonic=llm_start,
    )


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
