# -*- coding: utf-8 -*-
"""采纳反馈接口请求模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackActionRequest(BaseModel):
    """前端只提交动作，快照由后端按消息位置读取生成。"""

    action: Literal["accepted", "revoked"] = Field(
        ..., description="采纳动作: accepted=采纳, revoked=取消采纳",
    )

