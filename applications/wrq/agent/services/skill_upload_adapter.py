"""将资料/脚本上传入口映射为标准生成源，不读取或执行文件。"""
import hashlib
import re

from applications.wrq.agent.schemas.skill_package_schema import (
    MAX_SKILL_UPLOAD_FILES, SKILL_CLASS_IDS, SkillDeveloperForm, SkillEntryUploadSource, SkillPackageSource, SkillResourceBinding, SkillValidationReport, ValidationIssue,
)
from applications.wrq.agent.services.skill_package_builder import SkillPackageError, validate_source, markdown_body
from applications.wrq.agent.services.skill_resource_rules import resource_role, resource_name_key
from applications.wrq.platform_catalog import validate_application


def source_from_developer_form(form: SkillDeveloperForm, filenames: list[str], *,
                               technical_name: str | None = None, version: str = "1.0.0", validate_catalog: bool = True) -> SkillPackageSource:
    """统一入口的分类仅是目录组织约定，不执行或解压资源。"""
    report = SkillValidationReport()
    for field in ("skill_id", "skill_name", "description", "skill_class_id", "instructions"):
        if not getattr(form, field):
            report.missing_fields.append(ValidationIssue(field=field, reason="请补充此字段"))
    if (filenames or form.knowledge_base_ids) and not form.resource_usage:
        report.missing_fields.append(ValidationIssue(field="resource_usage", reason="选择知识库或上传资源后，请填写资源使用说明"))
    if validate_catalog and form.skill_class_id and form.skill_class_id not in SKILL_CLASS_IDS:
        report.errors.append(ValidationIssue(field="skill_class_id", reason="请选择平台提供的技能大类"))
    if len(form.resource_categories) != len(filenames):
        report.errors.append(ValidationIssue(field="resource_categories", reason="每个上传资源必须按文件顺序选择用途分类"))
    try:
        # 技能可选择具体应用，也可选择“全应用适用”（前端传递为 *）。
        if validate_catalog:
            validate_application(form.application, allow_all=True)
    except ValueError as exc:
        report.errors.append(ValidationIssue(field="application", reason=str(exc)))
    if form.skill_markdown is not None and markdown_body(form.skill_markdown) != form.instructions.strip():
        report.errors.append(ValidationIssue(field="skill_markdown", reason="Markdown 正文与执行指令不一致，请同步内容后保存"))
    if len(filenames) > MAX_SKILL_UPLOAD_FILES:
        report.errors.append(ValidationIssue(field="files", reason=f"每次最多上传 {MAX_SKILL_UPLOAD_FILES} 个文件"))
    if not report.finish().valid:
        raise SkillPackageError(report)

    resources, names = [], set()
    for index, filename in enumerate(filenames):
        try:
            role = resource_role(filename)
        except ValueError as exc:
            report.errors.append(ValidationIssue(field=f"files[{index}]", reason=str(exc)))
            continue
        key = resource_name_key(filename)
        if key in names:
            report.errors.append(ValidationIssue(field=f"files[{index}]", reason="同名资源已存在，请先移除旧文件"))
        names.add(key)
        category = form.resource_categories[index]
        role = "asset" if category == "template" else category
        resources.append(SkillResourceBinding(upload_index=index, role=role, category=category, usage=form.resource_usage))
    if not report.finish().valid:
        raise SkillPackageError(report)
    return SkillPackageSource(
        name=technical_name or "skill-" + hashlib.sha256(form.skill_id.encode()).hexdigest()[:24],
        display_name=form.skill_name, description=form.description, instructions=form.instructions,
        # 草稿/首次创建时数据库版本允许为 NULL；构建合同要求字符串，
        # 因此在适配层统一归一化为空字符串，避免空版本触发 Pydantic 类型错误。
        version=version or "", compatibility=form.compatibility, resource_usage=form.resource_usage,
        skill_class_id=str(form.skill_class_id), application=form.application, skill_markdown=form.skill_markdown,
        knowledge_base_ids=list(dict.fromkeys(str(v) for v in form.knowledge_base_ids)), resources=resources,
    )


def report_for_upload_entries(report: SkillValidationReport, form: SkillEntryUploadSource) -> SkillValidationReport:
    """将内部序号还原为前端对应入口，便于定位缺失说明、文件及路径错误。"""
    fields = ([f"reference_uploads[{index}]" for index in range(len(form.reference_uploads))]
              + [f"script_uploads[{index}]" for index in range(len(form.script_uploads))])
    files = ([f"reference_files[{index}]" for index in range(len(form.reference_uploads))]
             + [f"script_files[{index}]" for index in range(len(form.script_uploads))])
    for issue in report.missing_fields + report.errors + report.warnings:
        match = re.fullmatch(r"(resources|files)\[(\d+)\](.*)", issue.field)
        if not match:
            continue
        index = int(match[2])
        targets = files if match[1] == "files" else fields
        if match[1] == "resources":
            index -= len(form.resources)
        if 0 <= index < len(targets):
            issue.field = targets[index] + match[3]
    return report


def source_from_upload_entries(form: SkillEntryUploadSource, *, reference_count: int,
                               script_count: int) -> SkillPackageSource:
    report = SkillValidationReport()
    for field, count in (("reference_uploads", reference_count), ("script_uploads", script_count)):
        if len(getattr(form, field)) != count:
            report.errors.append(ValidationIssue(field=field, reason="每个上传文件必须按入口顺序提供一份说明，数量需一致"))
    if any(binding.upload_index is not None for binding in form.resources):
        report.errors.append(ValidationIssue(field="resources", reason="分入口上传的文件请放入 reference_uploads 或 script_uploads；resources 仅用于已有文档"))
    if len(form.resources) + len(form.reference_uploads) + len(form.script_uploads) > 100:
        report.errors.append(ValidationIssue(field="resources", reason="上传和挂载资源总数不能超过 100"))
    if reference_count + script_count > MAX_SKILL_UPLOAD_FILES:
        report.errors.append(ValidationIssue(field="files", reason=f"每次最多上传 {MAX_SKILL_UPLOAD_FILES} 个文件"))
    if report.errors:
        raise SkillPackageError(report)

    resources = list(form.resources)
    upload_index = 0
    for field, role in (("reference_uploads", "reference"), ("script_uploads", "script")):
        for spec in getattr(form, field):
            resources.append(SkillResourceBinding(upload_index=upload_index, role=role, **spec.model_dump()))
            upload_index += 1
    source = SkillPackageSource.model_validate({
        **form.model_dump(exclude={"reference_uploads", "script_uploads", "resources"}),
        "resources": resources,
    })
    report = report_for_upload_entries(validate_source(source), form)
    if not report.valid:
        raise SkillPackageError(report)
    return source
