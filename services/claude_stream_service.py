# -*- coding: utf-8 -*-
"""
@Author  : zhoushengjie
@Project : KeenRobot
@Module  : claude_stream_service.py
@DateTime: 2026/6/15

Claude Agent SDK 通用流式调用服务。
封装 SDK query + include_partial_messages 的 StreamEvent 解析逻辑，
各业务模块只需关注 prompt、skill 名称等差异化配置。
"""
from typing import AsyncIterator

from claude_agent_sdk import ClaudeAgentOptions, query, ResultMessage, HookMatcher
from claude_agent_sdk.types import StreamEvent

from configure import LOGGER, PROJECT_CONFIG
from services.agent_hooks import guard_bash_rm


_AUTO_MODE_PROMPT = (
    "[自动化模式] 这是后台自动执行任务，没有用户可回答你的问题。\n"
    "遇到需要用户确认的步骤时，请跳过确认、自动使用默认策略或最高匹配策略继续执行。\n"
    "不要询问用户任何问题，用 '默认策略' 或自动选择第一个可用选项继续。"
)


def build_stream_options(
    *,
    skills: list[str],
    output_dir: str,
    model: str,
    extra_system_prompt: str = "",
    max_turns: int = 400,
) -> ClaudeAgentOptions:
    """构建支持流式输出的 ClaudeAgentOptions。

    与 services.claude_agent_service.build_base_options 不同：
    1. 增加 include_partial_messages=True 以启用 StreamEvent
    2. 必须指定具体 model（流式不支持多模型轮询）
    """
    system_prompt = f"[输出目录] 本次任务的所有输出产物必须保存到：{output_dir}\n{_AUTO_MODE_PROMPT}"
    if extra_system_prompt:
        system_prompt += f"\n{extra_system_prompt}"

    return ClaudeAgentOptions(
        model=model,
        max_turns=max_turns,
        skills=skills,
        system_prompt=system_prompt,
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Skill"],
        setting_sources=["user", "project"],
        include_partial_messages=True,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Bash", hooks=[guard_bash_rm])
            ]
        },
        disallowed_tools=["AskUserQuestion"],
        cwd=PROJECT_CONFIG.WORKSPACE_DIR,
    )


async def stream_agent_query(
    prompt: str,
    options: ClaudeAgentOptions,
    log_tag: str = "Stream",
) -> AsyncIterator[dict]:
    """通用 Claude Agent SDK 流式调用，产出 SSE 事件字典。

    Args:
        prompt: 发送给 Agent 的提示词。
        options: 含 include_partial_messages=True 的配置。
        log_tag: 日志前缀标识（便于区分不同业务）。

    Yields:
        SSE 事件字典，结构为 {"event": str, "data": dict}。
        event 类型：
        - "text": 文本增量
        - "thinking_start": 思考块开始
        - "thinking": 思考增量
        - "tool_start": 工具调用开始
        - "tool_input": 工具输入增量
        - "tool_done": 工具调用完成
        - "done": 最终完成
        - "error": 错误
    """
    in_tool = False
    tool_name = ""
    result_text = ""

    LOGGER.info(f"【{log_tag}】开始流式调用: model={options.model}")

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, StreamEvent):
                event = message.event
                event_type = event.get("type")

                if event_type == "content_block_start":
                    content_block = event.get("content_block", {})
                    if content_block.get("type") == "tool_use":
                        tool_name = content_block.get("name", "")
                        in_tool = True
                        yield {"event": "tool_start", "data": {"type": "tool_start", "tool_name": tool_name}}
                    elif content_block.get("type") == "thinking":
                        yield {"event": "thinking_start", "data": {"type": "thinking_start"}}

                elif event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    delta_type = delta.get("type")

                    if delta_type == "text_delta" and not in_tool:
                        text_chunk = delta.get("text", "")
                        result_text += text_chunk
                        yield {"event": "text", "data": {"type": "text", "content": text_chunk}}
                    elif delta_type == "thinking_delta":
                        thinking_chunk = delta.get("thinking", "")
                        yield {"event": "thinking", "data": {"type": "thinking", "content": thinking_chunk}}
                    elif delta_type == "input_json_delta" and in_tool:
                        yield {
                            "event": "tool_input",
                            "data": {
                                "type": "tool_input",
                                "tool_name": tool_name,
                                "partial_json": delta.get("partial_json", ""),
                            },
                        }

                elif event_type == "content_block_stop":
                    if in_tool:
                        yield {"event": "tool_done", "data": {"type": "tool_done", "tool_name": tool_name}}
                        in_tool = False
                        tool_name = ""

            elif isinstance(message, ResultMessage):
                if message.is_error:
                    error_detail = "; ".join(message.errors) if message.errors else "unknown error"
                    LOGGER.error(f"【{log_tag}】Agent 返回错误: {error_detail}")
                    yield {"event": "error", "data": {"type": "error", "message": error_detail}}
                    return

                LOGGER.info(f"【{log_tag}】流式调用完成")
                yield {
                    "event": "done",
                    "data": {"type": "done", "result": message.result or result_text or ""},
                }

    except Exception as exc:
        LOGGER.exception(f"【{log_tag}】流式调用异常: {exc}")
        yield {"event": "error", "data": {"type": "error", "message": str(exc)}}


# 思考接口的事件白名单
THINKING_EVENT_WHITELIST = {"thinking", "thinking_start", "done", "error"}
