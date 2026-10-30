# -*- coding: utf-8 -*-
"""
@Author  : weixianzhe & zhoushengjie
@Project : KeenRobot
@Module  : claude_agent_service.py
@DateTime: 2026/6/12

Claude Agent SDK 通用调用服务。
封装 SDK 会话管理、多模型轮询、响应三层错误防御等通用逻辑，
各业务模块只需关注 prompt、skill 名称等差异化配置。
"""
import asyncio
from dataclasses import replace

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
)

from configure import LOGGER, PROJECT_CONFIG
from services.agent_hooks import guard_bash_rm

# 响应内容中视为错误指示的关键词
_ERROR_KEYWORDS = ["error", "exception", "failed"]

# 自动化模式的公共 system_prompt 片段
_AUTO_MODE_PROMPT = (
    "[自动化模式] 这是后台自动执行任务，没有用户可回答你的问题。\n"
    "遇到需要用户确认的步骤时（如系统类型匹配确认），请跳过确认、自动使用默认策略或最高匹配策略继续执行。\n"
    "不要询问用户任何问题，用 '默认策略' 或自动选择第一个可用选项继续。"
)


def build_base_options(
    *,
    skills: list[str],
    output_dir: str,
    extra_system_prompt: str = "",
    max_turns: int = 400,
    workspace_dir: str | None = None,
) -> ClaudeAgentOptions:
    """构建 ClaudeAgentOptions 基础配置。

    Args:
        skills: 要启用的 skill 名称列表。
        output_dir: Agent 输出产物的保存目录。
        extra_system_prompt: 附加到 system_prompt 的额外内容。
        max_turns: 最大交互轮次。
        workspace_dir: 可选的已校验 Skill 构建工作区；默认保持原工作区。

    Returns:
        配置好的 ClaudeAgentOptions 对象。
    """
    system_prompt = f"[输出目录] 本次任务的所有输出产物必须保存到：{output_dir}\n{_AUTO_MODE_PROMPT}"
    if extra_system_prompt:
        system_prompt += f"\n{extra_system_prompt}"

    return ClaudeAgentOptions(
        max_turns=max_turns,
        skills=skills,
        system_prompt=system_prompt,
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Skill"],
        setting_sources=["user", "project"],
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Bash", hooks=[guard_bash_rm])
            ]
        },
        disallowed_tools=["AskUserQuestion"],
        cwd=workspace_dir or PROJECT_CONFIG.WORKSPACE_DIR,
    )


async def run_with_model_pool(
    base_options: ClaudeAgentOptions,
    prompt: str,
) -> str:
    """多模型轮询执行 Claude Agent 会话。

    按 TEST_CASE_MODEL_POOL 配置的模型顺序依次尝试，
    单个模型超时或异常则跳过并记录日志，所有模型均失败时抛出 RuntimeError。
    每次尝试都会记录详细的错误信息以便排查。

    Args:
        base_options: 不含 model 字段的基础配置。
        prompt: 发送给 Agent 的提示词。

    Returns:
        Agent 执行成功后的响应文本。

    Raises:
        RuntimeError: 所有模型均失败。
    """
    models = PROJECT_CONFIG.TEST_CASE_MODEL_POOL.split(";")
    timeout = PROJECT_CONFIG.TEST_CASE_MODEL_TIMEOUT
    last_error = ""
    tried_count = 0

    LOGGER.info(f"【Agent】开始多模型轮询，模型池: {models}, 单模型超时: {timeout}s")

    for model in models:
        tried_count += 1
        options = replace(base_options, model=model)
        LOGGER.info(f"【Agent】尝试模型 {model} ({tried_count}/{len(models)})")
        try:
            result_text = await asyncio.wait_for(
                _run_session(options, prompt),
                timeout=timeout,
            )
            LOGGER.info(f"【Agent】模型 {model} 执行成功")
            return result_text

        except asyncio.TimeoutError:
            last_error = f"模型 {model} 执行超时（{timeout}秒）"
            LOGGER.warning(f"【Agent】{last_error}")
        except RuntimeError as exc:
            last_error = str(exc)
            LOGGER.warning(f"【Agent】模型 {model} 执行失败: {exc}")
        except Exception as exc:
            last_error = f"模型 {model} 执行异常: {type(exc).__name__}: {exc}"
            LOGGER.exception(f"【Agent】{last_error}")

    raise RuntimeError(f"所有模型均失败（{tried_count}次尝试），最后错误：{last_error}")


async def _run_session(
    options: ClaudeAgentOptions,
    prompt: str,
) -> str:
    """单次 Claude Agent SDK 会话。

    三层错误防御：
    1. ResultMessage.is_error — SDK 级别错误（API 429/500 等）
    2. result 为空 — Agent 无返回
    3. result 内容含错误关键词 — 语义级别错误
    """
    client = ClaudeSDKClient(options=options)
    try:
        await client.connect(prompt=prompt)
        result_text = ""
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                if message.is_error:
                    error_detail = "; ".join(message.errors) if message.errors else "unknown error"
                    result_snippet = (message.result or "")[:500]
                    raise RuntimeError(
                        f"Claude Agent SDK returned error: {error_detail}"
                        f" | result: {result_snippet}"
                    )
                msg_result = message.result or ""
                if msg_result:
                    result_text = msg_result
        if not result_text:
            raise RuntimeError("Claude Agent SDK returned empty result")
        if _contains_error(result_text):
            raise RuntimeError(
                f"Claude Agent SDK returned result with error indication: {result_text[:500]}"
            )
        return result_text
    finally:
        await client.disconnect()


def _contains_error(text: str) -> bool:
    """检查响应文本是否包含错误关键词。"""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in _ERROR_KEYWORDS)
