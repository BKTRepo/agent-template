from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import zipfile

import pytest
import yaml

from applications.wrq.agent.schemas.skill_package_schema import SkillPackageSource, SkillResourceBinding
from applications.wrq.agent.services.skill_package_builder import (
    ResolvedSkillResource, SkillPackageBuilder, SkillPackageError, safe_relative_path, validate_source,
)


def source(**changes):
    return SkillPackageSource(**{"name": "core-case-generator", "display_name": "核心系统用例生成",
                                 "description": '处理中文、冒号: 和 "引号"。\n生成边界用例。',
                                 "instructions": "根据需求生成正向、异常、边界测试用例。",
                                 "version": "0.1.0", **changes})


def resource(tmp_path, content=b"business rules", name="rules.md"):
    path = tmp_path / name
    path.write_bytes(content)
    return ResolvedSkillResource(0, path, name)


def test_missing_fields_report():
    report = validate_source(SkillPackageSource(resources=[SkillResourceBinding(upload_index=0)]))
    assert not report.valid
    assert {e.field for e in report.missing_fields} == {
        "name", "display_name", "description", "instructions", "version", "resources[0].role", "resources[0].usage"}


@pytest.mark.parametrize("value", ["../outside.py", "/absolute", "a/../../b", "C:/data", "a\\b", "a//b", "a/./b", "nul.txt", "COM1", "a."])
def test_reject_invalid_paths(value):
    with pytest.raises(ValueError):
        safe_relative_path(value)


@pytest.mark.parametrize("value", ["Core", "a--b", "-case", "case-", "中文", "nul"])
def test_reject_invalid_skill_names(value):
    assert not validate_source(source(name=value)).valid


def test_yaml_roundtrip_and_text_only_skill(tmp_path):
    builder = SkillPackageBuilder(tmp_path / "builds")
    form = source()
    built = builder.build(form, [], user_id=1, skill_id="skill-1")
    root = Path(built["skill_directory"])
    raw = (root / "SKILL.md").read_text(encoding="utf-8")
    metadata = yaml.safe_load(raw.split("---\n", 2)[1])
    assert metadata["description"] == form.description
    assert metadata["metadata"]["version"] == "0.1.0"
    assert metadata["metadata"]["display_name"] == form.display_name
    assert metadata["metadata"]["creator_id"] == "1"
    assert set(metadata) == {"name", "description", "metadata"}
    assert all(isinstance(value, str) for value in metadata["metadata"].values())
    assert "# 核心系统用例生成" in raw
    assert "## 功能说明" in raw and form.description in raw
    assert "## 执行指令" in raw and form.instructions in raw
    assert root.name == metadata["name"]
    assert {path.name for path in root.iterdir()} == {"SKILL.md"}
    assert "## 参考资料" not in raw and "## 脚本" not in raw and "## 模板与静态资源" not in raw
    assert root == Path(built["workspace_dir"]) / ".claude" / "skills" / form.name


def test_resources_and_download_preserve_bytes(tmp_path):
    original = resource(tmp_path, b"\x00\x01PDF bytes\xff", "规范 (1).pdf")
    form = source(resources=[SkillResourceBinding(upload_index=0, role="reference", usage="测试设计前读取业务规则。")])
    builder = SkillPackageBuilder(tmp_path / "builds")
    built = builder.build(form, [original], user_id=1, skill_id="skill-1")
    path = builder.archive_path(user_id=1, skill_id="skill-1", build_id=built["build_id"])
    with zipfile.ZipFile(path) as archive:
        assert archive.read(form.name + "/references/规范 (1).pdf") == original.path.read_bytes()
        assert all(name.startswith(form.name + "/") for name in archive.namelist())
    assert built["files"][1]["sha256"] == hashlib.sha256(original.path.read_bytes()).hexdigest()


def test_uploaded_script_is_never_executed(tmp_path):
    marker = tmp_path / "executed"
    content = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')".encode()
    form = source(resources=[SkillResourceBinding(upload_index=0, role="script", usage="检查输入时运行 python scripts/run.py。")])
    built = SkillPackageBuilder(tmp_path / "builds").build(form, [resource(tmp_path, content, "run.py")], user_id=1, skill_id="s")
    assert (Path(built["skill_directory"]) / "scripts/run.py").is_file()
    assert not marker.exists()


@pytest.mark.parametrize("reason", ["size", "hash", "link", "conflict", "missing"])
def test_failed_build_does_not_publish_partial_files(tmp_path, reason):
    builder = SkillPackageBuilder(tmp_path / "builds", max_file_bytes=2 if reason == "size" else 1000)
    bindings = [SkillResourceBinding(upload_index=0, role="reference", usage="生成前读取规则。",
                                    content_hash="0" * 64 if reason == "hash" else None)]
    resources = [resource(tmp_path)]
    form = source(resources=bindings, instructions="[missing](references/no.md)" if reason == "link" else "生成用例。")
    if reason == "conflict":
        form.resources.append(SkillResourceBinding(upload_index=1, role="reference", target_path="RULES.md", usage="补充规则。"))
        resources.append(ResolvedSkillResource(1, resources[0].path, "other.md"))
    if reason == "missing":
        resources = []
    with pytest.raises(SkillPackageError):
        builder.build(form, resources, user_id=1, skill_id="skill-1")
    assert not list((tmp_path / "builds").glob("**/manifest.json"))
    assert not list((tmp_path / "builds").glob("**/.building-*"))


def test_multiple_resources_have_no_aggregate_size_limit(tmp_path):
    original = resource(tmp_path, b"abcd")
    form = source(resources=[SkillResourceBinding(upload_index=0, role="reference", usage="读取规则。"),
                             SkillResourceBinding(upload_index=1, role="asset", usage="采用输出模板。")])
    builder = SkillPackageBuilder(tmp_path / "builds", max_file_bytes=4)
    built = builder.build(form,
        [original, ResolvedSkillResource(1, original.path, original.filename)], user_id=1, skill_id="s")
    assert sum(entry['size'] for entry in built['files'][1:]) == 8
    builder.read(user_id=1, skill_id="s", build_id=built['build_id'], verify=True)


def test_default_resource_limits_are_50_mib(tmp_path):
    from configure.project_config import ProjectConfig

    assert ProjectConfig.model_fields['SKILL_RESOURCE_MAX_BYTES'].default == 50 * 1024 * 1024
    assert ProjectConfig.model_fields['SKILL_RESOURCE_TOTAL_MAX_BYTES'].default == 50 * 1024 * 1024
    assert SkillPackageBuilder(tmp_path).max_file_bytes == 50 * 1024 * 1024


@pytest.mark.parametrize('size', [3, 4, 5])
def test_copied_resource_file_size_boundary(tmp_path, size):
    original = resource(tmp_path, b'x' * size)
    form = source(resources=[SkillResourceBinding(upload_index=0, role='reference', usage='读取规则')])
    builder = SkillPackageBuilder(tmp_path / 'builds', max_file_bytes=4)
    if size > 4:
        with pytest.raises(SkillPackageError) as exc:
            builder.build(form, [original], user_id=1, skill_id='s')
        assert exc.value.report.errors[0].field == 'resources[0]'
        assert not list(builder.root.glob('**/manifest.json'))
        assert not list(builder.root.glob('**/.building-*'))
    else:
        built = builder.build(form, [original], user_id=1, skill_id='s')
        assert built['files'][1]['size'] == size


def test_concurrent_builds_preserve_previous_version(tmp_path):
    builder = SkillPackageBuilder(tmp_path / "builds")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda v: builder.build(source(version=v), [], user_id=1, skill_id="s"), ["0.1.0", "0.2.0"]))
    assert results[0]["build_id"] != results[1]["build_id"]
    for result in results:
        assert builder.read(user_id=1, skill_id="s", build_id=result["build_id"], verify=True)["version"] == result["version"]


@pytest.mark.parametrize("tamper", ["changed", "extra", "zip"])
def test_detect_directory_or_zip_tampering(tmp_path, tamper):
    builder = SkillPackageBuilder(tmp_path / "builds")
    built = builder.build(source(), [], user_id=1, skill_id="s")
    if tamper == "zip":
        (Path(built["workspace_dir"]) / "package.zip").write_bytes(b"modified")
    else:
        (Path(built["skill_directory"]) / ("SKILL.md" if tamper == "changed" else "extra.py")).write_text("changed")
    with pytest.raises(SkillPackageError):
        builder.read(user_id=1, skill_id="s", build_id=built["build_id"], verify=True)


def test_build_directory_cannot_be_read_by_other_user(tmp_path):
    builder = SkillPackageBuilder(tmp_path / "builds")
    built = builder.build(source(), [], user_id=1, skill_id="s")
    with pytest.raises(FileNotFoundError):
        builder.read(user_id=2, skill_id="s", build_id=built["build_id"])


def test_local_links_inside_code_fences_are_not_references(tmp_path):
    SkillPackageBuilder(tmp_path / "builds").build(source(instructions="```md\n[示例](not-real.md)\n```"), [], user_id=1, skill_id="s")


def test_environment_and_platform_metadata_are_serialized_as_strings(tmp_path):
    environment = 'Python 3.11+；依赖: PyYAML\n网络访问: "无需"'
    form = source(compatibility=environment, skill_class_id="SKILL-CASE-001", application="核心系统", system="旧系统",
                  team="测试一组", model_tier="standard")
    built = SkillPackageBuilder(tmp_path / "builds").build(form, [], user_id=7, skill_id="s")
    raw = (Path(built["skill_directory"]) / "SKILL.md").read_text(encoding="utf-8")
    header = yaml.safe_load(raw.split("---\n", 2)[1])
    assert header["compatibility"] == environment
    assert set(header) == {"name", "description", "compatibility", "metadata"}
    assert header["metadata"] == {
        "version": "0.1.0", "skill_id": "s", "creator_id": "7", "display_name": form.display_name,
        "skill_class_id": "SKILL-CASE-001", "application": "核心系统", "model_tier": "standard"}
    assert built["source"]["compatibility"] == environment


@pytest.mark.parametrize("compatibility", ["", "  \n\t "])
def test_empty_environment_is_omitted(tmp_path, compatibility):
    built = SkillPackageBuilder(tmp_path / "builds").build(source(compatibility=compatibility), [], user_id=1, skill_id="s")
    raw = (Path(built["skill_directory"]) / "SKILL.md").read_text(encoding="utf-8")
    assert "compatibility" not in yaml.safe_load(raw.split("---\n", 2)[1])


@pytest.mark.parametrize("usage", ["", " \n\t "])
def test_uploaded_resource_requires_usage_before_any_files_are_created(tmp_path, usage):
    builder = SkillPackageBuilder(tmp_path / "builds")
    form = source(resources=[SkillResourceBinding(upload_index=0, role="reference", usage=usage)])
    with pytest.raises(SkillPackageError) as exc:
        builder.build(form, [resource(tmp_path)], user_id=1, skill_id="s")
    assert {issue.field for issue in exc.value.report.missing_fields} == {"resources[0].usage"}
    assert not builder.root.exists()


def test_resource_sections_links_and_multiline_usage_preserve_source_content(tmp_path):
    usage = "生成前读取规则。\n- 不编造缺失信息\n- 记录待补充的问题"
    form = source(resources=[
        SkillResourceBinding(upload_index=0, role="reference", usage=usage),
        SkillResourceBinding(upload_index=1, role="script", usage="检查输入时调用：python scripts/check.py input.json"),
        SkillResourceBinding(upload_index=2, role="asset", usage="输出时采用模板字段。")])
    original = resource(tmp_path, "演示规则：金额必须大于零。".encode(), "业务规则 (1).md")
    resolved = [original, ResolvedSkillResource(1, original.path, "check.py"),
                ResolvedSkillResource(2, original.path, "template.json")]
    builder = SkillPackageBuilder(tmp_path / "builds")
    built = builder.build(form, resolved, user_id=1, skill_id="s")
    raw = (Path(built["skill_directory"]) / "SKILL.md").read_text(encoding="utf-8")
    assert "## 参考资料" in raw and "## 脚本" in raw and "## 模板与静态资源" in raw
    assert "references/%E4%B8%9A%E5%8A%A1%E8%A7%84%E5%88%99%20%281%29.md" in raw
    assert "  生成前读取规则。\n  - 不编造缺失信息\n  - 记录待补充的问题" in raw
    assert "python scripts/check.py input.json" in raw
    assert "输出时采用模板字段。" in raw
    assert built["files"][1]["usage"] == usage
    builder.read(user_id=1, skill_id="s", build_id=built["build_id"], verify=True)


def test_missing_source_file_returns_field_error_and_cleans_staging(tmp_path):
    builder = SkillPackageBuilder(tmp_path / "builds")
    form = source(resources=[SkillResourceBinding(upload_index=0, role="reference", usage="生成前读取。")])
    with pytest.raises(SkillPackageError) as exc:
        builder.build(form, [ResolvedSkillResource(0, tmp_path / "absent.md", "absent.md")], user_id=1, skill_id="s")
    assert exc.value.report.errors[0].field == "resources[0]"
    assert not list(builder.root.glob("**/manifest.json"))
    assert not list(builder.root.glob("**/.building-*"))


def test_usage_local_links_must_point_to_actual_files(tmp_path):
    form = source(resources=[SkillResourceBinding(upload_index=0, role="reference", usage="参考[补充规则](references/absent.md)。")])
    with pytest.raises(SkillPackageError) as exc:
        SkillPackageBuilder(tmp_path / "builds").build(form, [resource(tmp_path)], user_id=1, skill_id="s")
    assert "本地资源引用不存在" in exc.value.report.errors[0].reason
