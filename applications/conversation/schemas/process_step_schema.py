# -*- coding: utf-8 -*-
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

ProcessStepStatus = Literal["running", "done", "error"]
ProcessStepType = Literal["reasoning", "skill", "mcp"]


class ProcessStepBase(BaseModel):
    type: ProcessStepType = Field(..., description="步骤类型")
    status: ProcessStepStatus = Field(default="running", description="步骤状态")


class ReasoningStep(ProcessStepBase):
    type: Literal["reasoning"] = "reasoning"
    content: str = Field(default="", description="推理内容")


class SkillStep(ProcessStepBase):
    type: Literal["skill"] = "skill"
    skill_id: Optional[str] = Field(default=None, description="技能ID")
    name: Optional[str] = Field(default=None, description="技能名称")
    input: Optional[dict[str, Any]] = Field(default=None, description="技能输入")
    output: Optional[str] = Field(default=None, description="技能输出")


class McpStep(ProcessStepBase):
    type: Literal["mcp"] = "mcp"
    server: Optional[str] = Field(default=None, description="MCP 服务名")
    tool: Optional[str] = Field(default=None, description="工具名")
    arguments: Optional[dict[str, Any]] = Field(default=None, description="工具参数")
    result: Optional[str] = Field(default=None, description="工具结果")


ProcessStep = Union[ReasoningStep, SkillStep, McpStep]

STEP_TYPE_LABELS = {
    "reasoning": "深度思考",
    "skill": "技能调用",
    "mcp": "MCP 工具",
}
