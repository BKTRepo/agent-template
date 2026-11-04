"""开发者中心在线调试接口的文本字段模型。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field


class OnlineModelDebugRequest(BaseModel):
    """开发者中心“运行调试”表单中的文本字段。"""

    # 技能自增整数编号，与技能主表的 signed INT(11) 保持一致。
    skill_id: Annotated[int, Field(ge=1, le=2147483647)]
    # Skill 定义，使用 Markdown 文本。最大约 10 万字符。
    skill_definition: Annotated[str, Field(min_length=1, max_length=100_000)]
    # 对话输入，即用户在页面上填写的本次调试诉求。最大 2 万字符。
    conversation_input: Annotated[str, Field(max_length=20_000)] = ""
