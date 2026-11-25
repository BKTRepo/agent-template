from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ClassId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SkillClassCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RequiredText = Field(max_length=20)
    test_stage_id: ClassId
    description: RequiredText = Field(max_length=500)
    input_description: RequiredText = Field(max_length=200)
    output_description: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(default="", max_length=200)
    template: str = Field(min_length=1, max_length=100000)

    @field_validator('template')
    @classmethod
    def nonempty_template(cls, value):
        if not value.strip():
            raise ValueError('请填写Skill模板')
        return value


class SkillClassUpdate(SkillClassCreate):
    class_id: ClassId
    expected_revision: ClassId


class SkillClassRemove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_id: ClassId
    expected_revision: ClassId
