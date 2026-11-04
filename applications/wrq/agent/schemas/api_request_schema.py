"""WRQ HTTP 请求：GET 使用查询参数，POST 的编号和业务字段统一放在请求体。"""
from pydantic import BaseModel, ConfigDict, Field

from .agent_schema import (
    DeveloperDebugResult, DeveloperSkillForm, McpServerUpdate,
    OfflineSkillRequest, SkillUpdate,
)
from .skill_package_schema import SkillDefinitionEdit, SkillPackageSource


class SkillIdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    skill_id: int = Field(ge=1, le=2147483647, description="技能编号")


class DeveloperSkillSaveRequest(DeveloperSkillForm):
    skill_id: int = Field(ge=1, le=2147483647, description="技能编号")


class OfflineSkillBody(OfflineSkillRequest):
    skill_id: int = Field(ge=1, le=2147483647, description="技能编号")


class RegisterDebugRunRequest(DeveloperDebugResult):
    skill_id: int = Field(ge=1, le=2147483647, description="技能编号")


class SkillUpdateBody(SkillUpdate):
    skill_id: int = Field(ge=1, le=2147483647, description="技能编号")


class McpIdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mcp_id: str = Field(min_length=1, max_length=64, description="MCP 服务编号")


class McpUpdateBody(McpServerUpdate):
    mcp_id: str = Field(min_length=1, max_length=64, description="MCP 服务编号")


class SkillDefinitionSaveRequest(SkillDefinitionEdit):
    skill_id: int = Field(ge=1, le=2147483647, description="技能编号")


class SkillPackageRequest(SkillPackageSource):
    skill_id: int = Field(ge=1, le=2147483647, description="技能编号")


def business_payload(request: BaseModel, model: type[BaseModel], identifier="skill_id"):
    """隔离路由定位字段，保留业务模型原有的字段及未填写字段语义。"""
    return model.model_validate(request.model_dump(exclude={identifier}, exclude_unset=True))
