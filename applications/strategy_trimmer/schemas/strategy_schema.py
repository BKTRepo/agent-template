from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChangeType = Literal['framework', 'database', 'middleware', 'os', 'browser']
ToolId = Literal['automation', 'precision', 'toolbox', 'ai', 'performance']
Text = Annotated[str, Field(max_length=4000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class SystemSelection(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    testDept: Literal['是', '部分', '否', '待确认']


class Decision(StrictModel):
    status: Literal['必测', '条件测试', '裁剪']
    reason: Text = ''

    @model_validator(mode='after')
    def require_cut_reason(self):
        if self.status == '裁剪' and not self.reason:
            raise ValueError('裁剪项必须填写备注或替代验证依据')
        return self


class ToolChoice(StrictModel):
    decision: Literal['必用', '条件使用', '不使用']


class ExtraGate(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    rule: Annotated[str, Field(min_length=1, max_length=2000)]
    kind: Literal['硬性', '软性', '红线']
    checked: bool = False


class Stakeholder(StrictModel):
    role: Annotated[str, Field(min_length=1, max_length=100)]
    name: Annotated[str, Field(min_length=1, max_length=100)]
    duty: Annotated[str, Field(min_length=1, max_length=2000)]


class GenerateRequest(StrictModel):
    reqId: Annotated[str, Field(max_length=100)] = ''
    name: Annotated[str, Field(min_length=1, max_length=200)]
    duration: Literal['≤5个工作日', '6-15个工作日', '>15个工作日']
    changes: Annotated[list[ChangeType], Field(min_length=1, max_length=5)]
    systems: Annotated[list[SystemSelection], Field(min_length=1, max_length=50)]
    functionDecisions: dict[ChangeType, Decision] = Field(default_factory=dict)
    nfDecisions: dict[ChangeType, Decision] = Field(default_factory=dict)
    toolChoices: dict[ToolId, ToolChoice] = Field(default_factory=dict)
    extraGates: Annotated[list[ExtraGate], Field(max_length=50)] = Field(default_factory=list)
    stakeholders: Annotated[list[Stakeholder], Field(min_length=1, max_length=50)]
    collabConfirmed: Literal[True]

    @model_validator(mode='after')
    def confirm_scope_and_gates(self):
        if len(set(self.changes)) != len(self.changes):
            raise ValueError('改造类型不能重复')
        for decisions in (self.functionDecisions, self.nfDecisions):
            if set(decisions) - set(self.changes):
                raise ValueError('裁剪结论只能包含本次选择的改造类型')
        if any(g.kind == '硬性' and not g.checked for g in self.extraGates):
            raise ValueError('额外硬性门禁必须完成确认')
        return self


class GenerateResponse(BaseModel):
    filename: str
    markdown: str
    documentId: str
    downloadUrl: str
    createdAt: str
    reqId: str
    name: str
    configVersion: str


class GenerateEnvelope(BaseModel):
    code: str
    status: str
    message: str | None
    data: GenerateResponse
    total: int | None = None
