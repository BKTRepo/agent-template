"""新表单字段合同：接受选填配置和资源说明，拒绝无效类型及客户端身份覆盖。"""
import pytest
from pydantic import ValidationError

from applications.agent.schemas.skill_package_schema import (
    SkillPackageSource, SkillResourceBinding,
)


def test_new_form_fields_survive_json_roundtrip():
    source = SkillPackageSource.model_validate_json('''{
        "name": "core-case-generator",
        "display_name": "核心系统用例生成",
        "description": "根据需求生成测试用例，适用于功能测试设计。",
        "instructions": "读取需求与参考资料后生成用例。",
        "version": "0.1.0",
        "compatibility": "  Python 3.12；需要读取本地文件  ",
        "resources": [{
            "upload_index": 0,
            "role": "script",
            "usage": "  检查输入时调用 python scripts/check_input.py input.json  "
        }]
    }''')
    restored = SkillPackageSource.model_validate_json(source.model_dump_json())
    assert restored.compatibility == "Python 3.12；需要读取本地文件"
    assert restored.resources[0].usage == (
        "检查输入时调用 python scripts/check_input.py input.json"
    )
    assert restored.resources[0].upload_index == 0
    assert restored.resources[0].role == "script"


def test_existing_requests_and_incomplete_drafts_remain_accepted():
    source = SkillPackageSource(resources=[{"upload_index": 0, "role": "reference"}])
    assert source.compatibility == ""
    assert source.resources[0].usage == ""
    assert source.name == ""
    assert source.instructions == ""


def test_whitespace_only_optional_text_becomes_empty():
    source = SkillPackageSource(compatibility=" \n\t ",
                               resources=[{"upload_index": 0, "usage": " \n\t "}])
    assert source.compatibility == ""
    assert source.resources[0].usage == ""


@pytest.mark.parametrize("value", ["x" * 501, {"python": "3.12"}, [], None])
def test_compatibility_rejects_overlong_or_non_string_values(value):
    with pytest.raises(ValidationError) as error:
        SkillPackageSource(compatibility=value)
    assert error.value.errors()[0]["loc"] == ("compatibility",)


def test_compatibility_accepts_exact_length_limit():
    assert len(SkillPackageSource(compatibility="x" * 500).compatibility) == 500


@pytest.mark.parametrize("value", ["x" * 10_001, {"command": "python run.py"}, [], None])
def test_nested_usage_reports_its_field_location(value):
    with pytest.raises(ValidationError) as error:
        SkillPackageSource(resources=[{"upload_index": 0, "usage": value}])
    assert error.value.errors()[0]["loc"] == ("resources", 0, "usage")


@pytest.mark.parametrize("role", ["reference", "script", "asset"])
def test_internal_resource_roles_remain_compatible(role):
    binding = SkillResourceBinding(document_id="document-1", role=role,
                                   usage="按需读取资源")
    assert binding.role == role
    assert binding.document_id == "document-1"


def test_usage_normalization_preserves_resource_path():
    binding = SkillResourceBinding(upload_index=0, role="reference",
                                   target_path="规则 文档.md", usage="  读取规则  ")
    assert binding.target_path == "规则 文档.md"
    assert binding.usage == "读取规则"


@pytest.mark.parametrize("field", ["creator_id", "maintainer_id", "user_id"])
def test_client_cannot_supply_identity_fields(field):
    with pytest.raises(ValidationError) as error:
        SkillPackageSource.model_validate({field: "other-user"})
    assert error.value.errors()[0]["type"] == "extra_forbidden"
    assert error.value.errors()[0]["loc"] == (field,)
