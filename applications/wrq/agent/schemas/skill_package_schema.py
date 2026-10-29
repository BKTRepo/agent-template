"""开发者表单合同；允许空字段，以返回可供前端补填的业务校验报告。"""
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints


# 上传入口每次最多 5 个文件；知识库展开的原文件不是本次直接上传。
MAX_SKILL_UPLOAD_FILES = 100  # 防止异常 multipart；定稿不再沿用旧的 5 个文件规则。

SKILL_CLASS_IDS = {"SKILL-POINT-005", "SKILL-CASE-001", "SKILL-BUG-004",
                   "SKILL-REPORT-006", "SKILL-DATA-002", "SKILL-UI-007"}


class SkillResourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str | None = Field(default=None, max_length=64)
    upload_index: int | None = Field(default=None, ge=0)
    role: Literal["script", "reference", "asset"] | None = Field(
        default=None, description="内部文件用途，由上传入口固定设置，不增加用户分类填写项")
    usage: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(
        default="", max_length=10_000,
        description="资源使用说明：何时使用、用途及脚本调用方式；上传资源生成时必填，草稿允许为空")
    target_path: str | None = Field(default=None, max_length=255,
                                    description="用途目录下的相对路径；为空时沿用原文件名")
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$",
                                     description="可选，固定挂载文件的 SHA256")
    category: Literal["reference", "template", "asset", "script"] | None = None


class SkillPackageSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(default="", max_length=64, description="Skill 技术名")
    display_name: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=1024)
    instructions: str = Field(default="", max_length=100_000)
    compatibility: str = Field(
        default="", max_length=500,
        description="选填运行环境要求，如 Python 版本、依赖包、网络要求；为空时不输出到 SKILL.md")
    # None 表示旧合同；新表单使用独立的统一说明，不再拼进 instructions。
    resource_usage: str | None = Field(default=None, max_length=10_000)
    version: str = Field(default="", max_length=64)
    application: str | None = Field(default=None, max_length=128)
    skill_markdown: str | None = Field(default=None, max_length=200_000)
    # 当前仓库尚无技能类/团队模型，这些值仅作为平台元信息，不表示已验证归属。
    skill_class_id: str | None = Field(default=None, max_length=64)
    system: str | None = Field(default=None, max_length=128)
    team: str | None = Field(default=None, max_length=128)
    model_tier: str | None = Field(default=None, max_length=64)
    resources: list[SkillResourceBinding] = Field(default_factory=list, max_length=100)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=100,
                                        description="将有权限的知识库原文件快照到 references/")


class SkillUploadFileSpec(BaseModel):
    """单个上传入口的文件说明；用途和上传序号由后端固定，不接受手填。"""
    model_config = ConfigDict(extra="forbid")

    usage: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(default="", max_length=10_000)
    target_path: str | None = Field(default=None, max_length=255,
                                    description="可选内部相对路径；省略时沿用文件名，不是服务器路径")
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SkillEntryUploadSource(SkillPackageSource):
    """参考资料/脚本入口的请求合同，生成前统一映射为 SkillPackageSource。"""
    reference_uploads: list[SkillUploadFileSpec] = Field(default_factory=list, max_length=100)
    script_uploads: list[SkillUploadFileSpec] = Field(default_factory=list, max_length=100)


class SkillDeveloperForm(BaseModel):
    """八项表单及页面携带的技能 ID；拒绝客户端指定身份和内部生成参数。"""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    skill_id: str = Field(default="", max_length=64)
    skill_name: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=1024)
    version: str = Field(default="", max_length=64)
    skill_class_id: int | str = Field(default="")
    application_paso: str | None = Field(default=None, max_length=100,
        validation_alias=AliasChoices('application_paso', 'application'))
    resource_categories: list[Literal["reference", "template", "asset", "script"]] = Field(default_factory=list, max_length=100)
    skill_markdown: str | None = Field(default=None, max_length=200_000)
    expected_version: str | None = Field(default=None, max_length=64)
    instructions: str = Field(default="", max_length=100_000)
    knowledge_base_ids: list[int | Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=100)
    resource_usage: str = Field(default="", max_length=10_000)
    compatibility: str = Field(default="", max_length=500)

    @property
    def application(self):
        return self.application_paso


class ValidationIssue(BaseModel):
    field: str
    reason: str


class SkillDefinitionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    markdown: str = Field(min_length=1, max_length=200_000)
    expected_version: str = Field(min_length=1, max_length=64)


class SkillValidationReport(BaseModel):
    valid: bool = False
    missing_fields: list[ValidationIssue] = Field(default_factory=list)
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)

    def finish(self):
        self.valid = not (self.missing_fields or self.errors)
        return self
