import pytest
from pydantic import ValidationError

from applications.agent.schemas.skill_package_schema import SkillEntryUploadSource
from applications.agent.services.skill_package_builder import SkillPackageError
from applications.agent.services.skill_upload_adapter import source_from_upload_entries


FORM = {"name": "case-generator", "display_name": "用例生成", "description": "按需求生成用例，用于功能测试设计。",
        "instructions": "读取需求后生成测试用例。", "version": "0.1.0"}


def test_entries_assign_roles_and_indexes_without_user_classification():
    form = SkillEntryUploadSource(**FORM, resources=[{"document_id": "doc-1", "role": "reference"}],
                                 reference_uploads=[{"usage": "  读取规则。  "}],
                                 script_uploads=[{"usage": "运行脚本。", "target_path": "tools/check.py"}])
    source = source_from_upload_entries(form, reference_count=1, script_count=1)
    assert [(item.document_id, item.upload_index, item.role) for item in source.resources] == [
        ("doc-1", None, "reference"), (None, 0, "reference"), (None, 1, "script")]
    assert source.resources[1].usage == "读取规则。"
    assert source.resources[2].target_path == "tools/check.py"
    assert "script_uploads" not in source.model_dump()
    assert len(form.resources) == 1


@pytest.mark.parametrize("field", ["reference_uploads", "script_uploads"])
def test_missing_usage_is_reported_against_original_entry(field):
    form = SkillEntryUploadSource(**FORM, **{field: [{"usage": " \n "}]})
    with pytest.raises(SkillPackageError) as exc:
        source_from_upload_entries(form, reference_count=int(field == "reference_uploads"),
                                   script_count=int(field == "script_uploads"))
    assert {issue.field for issue in exc.value.report.missing_fields} == {f"{field}[0].usage"}


@pytest.mark.parametrize("extra", [{"role": "asset"}, {"upload_index": 0}, {"document_id": "fake"}])
def test_entry_specs_cannot_override_backend_classification(extra):
    with pytest.raises(ValidationError) as exc:
        SkillEntryUploadSource(**FORM, script_uploads=[{"usage": "运行。", **extra}])
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


def test_combined_resource_limit_and_legacy_upload_bindings_are_rejected():
    form = SkillEntryUploadSource(**FORM, reference_uploads=[{"usage": "读取。"}] * 60,
                                 script_uploads=[{"usage": "运行。"}] * 41)
    with pytest.raises(SkillPackageError) as exc:
        source_from_upload_entries(form, reference_count=60, script_count=41)
    assert exc.value.report.errors[0].field == "resources"
    assert "100" in exc.value.report.errors[0].reason
    form = SkillEntryUploadSource(**FORM, resources=[{"upload_index": 0, "role": "script", "usage": "运行。"}])
    with pytest.raises(SkillPackageError) as exc:
        source_from_upload_entries(form, reference_count=0, script_count=0)
    assert "resources 仅用于已有文档" in exc.value.report.errors[0].reason
