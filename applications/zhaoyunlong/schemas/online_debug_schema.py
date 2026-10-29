"""开发者中心在线调试接口的文本字段模型。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field


class OnlineModelDebugRequest(BaseModel):
    """开发者中心“运行调试”表单中的文本字段。"""

    # 技能业务标识，用于后续查询该技能最近一次调试任务。最大 128 个字符。
    skill_id: Annotated[str, Field(min_length=1, max_length=128)]
    # Skill 定义，使用 Markdown 文本。最大约 10 万字符。
    skill_definition: Annotated[str, Field(min_length=1, max_length=100_000)]
    # 对话输入，即用户在页面上填写的本次调试诉求。最大 2 万字符。
    conversation_input: Annotated[str, Field(max_length=20_000)] = ""
