"""定稿知识库合同：身份、版本与路径均由服务器确定。"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class KnowledgeForm(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    knowledge_name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=10_000)
    tag: Literal["general", "custom"]
    application: str = Field(min_length=1, max_length=128)
    is_public: bool = True
    change_summary: str = Field(default="", max_length=10_000)
    expected_version: str | None = None
    # 编辑时显式声明保留的文件，避免把“没重新上传”误解成删除。
    retained_document_ids: list[str] | None = None


class DocumentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1)
    change_summary: str = Field(min_length=1, max_length=10_000)
    expected_generation: int = Field(ge=1)


class KnowledgeMount(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    skill_ids: list[str] = Field(min_length=1, max_length=100)
    resource_usage: str = Field(min_length=1, max_length=10_000)


def next_version(revision: int) -> str:
    return f"V1.0.{revision}"
