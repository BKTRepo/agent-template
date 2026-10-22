# -*- coding: utf-8 -*-
"""
@Author  : weixianzhe
@Project : KeenRobot
@Module  : agent_hooks.py
@DateTime: 2026/6/11
"""
import os
import re
import shlex
from typing import Any

from configure import PROJECT_CONFIG


async def guard_bash_rm(input_data: dict[str, Any], tool_use_id: str, context: Any) -> dict[str, Any]:
    command = input_data.get("tool_input", {}).get("command", "")
    if not isinstance(command, str) or not command.strip():
        return {}

    # 仅拦截 rm 命令
    if not re.match(r"^\s*rm\b", command.strip()):
        return {}

    targets = _extract_rm_targets(command)
    if not targets:
        # rm 没有指定文件，拒绝（例如 裸 rm -rf）
        return {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": "rm without explicit targets is not allowed.",
            }
        }

    allowed_dir = PROJECT_CONFIG.WORKSPACE_DIR.rstrip("/\\")
    for target in targets:
        if _is_outside_allowed(target, allowed_dir):
            return {
                "hookSpecificOutput": {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"rm target '{target}' is outside the allowed working directory ({allowed_dir}).",
                }
            }

    # 所有目标都在工作目录内 → 批准
    return {"hookSpecificOutput": {"permissionDecision": "approve"}}


def _extract_rm_targets(command: str) -> list[str]:
    try:
        parts = shlex.split(command)
    except ValueError:
        return []
    return [p for p in parts[1:] if not p.startswith("-")]


def _is_outside_allowed(target: str, allowed_dir: str) -> bool:
    expanded = os.path.expanduser(target)
    if not os.path.isabs(expanded):
        resolved = os.path.realpath(os.path.join(allowed_dir, expanded))
    else:
        resolved = os.path.realpath(expanded)
    return os.path.commonpath([resolved, allowed_dir]) != allowed_dir
