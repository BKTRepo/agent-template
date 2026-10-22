"""定稿增量覆盖：分类、自动版本、Markdown 保存及知识库真实原文件挂载。"""
import io
import json
from pathlib import Path
import zipfile

import pytest

from applications.agent.models.agent_model import Skill
from applications.agent.services.skill_package_service import SkillPackageService
from applications.agent.services.skill_package_builder import SkillPackageBuilder
from test_skill_developer_form import form, submit
from test_skill_package_api import setup, token
from test_platform_knowledge import kb_setup, save


@pytest.mark.asyncio
async def test_manual_categories_template_and_asset_keep_original_bytes(setup):
    client, owner, _, skill = setup
    files = [("files", ("template.md", b"# Template")), ("files", ("diagram.png", b"PNG image unchanged")),
             ("files", ("run.py", b"raise RuntimeError('never execute')"))]
    data = form(skill, application="核心系统", resource_usage="按模板生成用例，先看流程图，脚本由运行端使用。",
                resource_categories=["template", "asset", "script"], version="999.999.999")
    result = await submit(client, owner, data, files)
    assert result["status"] == "success", result
    built = result["data"]
    assert built["version"] == "1.0.0"
    assert [f["category"] for f in built["files"][1:]] == ["template", "asset", "script"]
    assert [f["path"] for f in built["files"][1:]] == ["assets/template.md", "assets/diagram.png", "scripts/run.py"]
    download = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        for row, (_, (_, content)) in zip(built["files"][1:], files):
            assert archive.read(f"{built['name']}/{row['path']}") == content


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"resource_categories": []}, {"application": "自由输入的无效应用"}, {"skill_class_id": "unknown"}])
async def test_missing_classification_and_invalid_catalog_values_roll_back(setup, changes):
    client, owner, _, skill = setup
    result = await submit(client, owner, form(skill, resource_usage="读取附件", **changes), [("files", ("rules.md", b"rule"))])
    assert result["status"] == "failure"
    await skill.refresh_from_db()
    assert skill.config is None and skill.name == "核心用例生成"


@pytest.mark.asyncio
async def test_markdown_edit_version_and_conflict_do_not_duplicate_resources(setup):
    client, owner, other, skill = setup
    first = (await submit(client, owner, form(skill, resource_usage="读取规则"), [("files", ("rules.md", b"rule"))]))["data"]
    path = f"/skills/{skill.id}/definition"
    current = (await client.get(path, headers=token(owner))).json()["data"]
    markdown = current["markdown"].replace("读取需求并生成用例。", "先核对需求，再设计异常场景。")
    edited = (await client.put(path, headers=token(owner), json={"markdown": markdown, "expected_version": "1.0.0"})).json()
    assert edited["status"] == "success", edited
    assert edited["data"]["version"] == "1.0.1"
    assert "先核对需求" in edited["data"]["source"]["instructions"]
    current = (await client.get(path, headers=token(owner))).json()["data"]
    assert current["markdown"].count("<!-- platform-resources:start -->") == 1
    assert current["markdown"].count("[参考资料 1]") == 1
    assert (Path(first["skill_directory"]) / "references/rules.md").read_bytes() == b"rule"
    conflict = (await client.put(path, headers=token(owner), json={"markdown": markdown, "expected_version": "1.0.0"})).json()
    assert conflict["status"] == "failure" and conflict["data"]["errors"][0]["field"] == "expected_version"
    assert (await client.put(path, headers=token(other), json={"markdown": markdown, "expected_version": "1.0.1"})).json()["status"] == "failure"


@pytest.mark.asyncio
@pytest.mark.parametrize("markdown", ["---\nname: [broken\n---\ntext", "[missing](../out.md)", "---\nname: x\n---\n"])
async def test_bad_markdown_leaves_current_build_and_version_unchanged(setup, markdown):
    client, owner, _, skill = setup
    first = (await submit(client, owner, form(skill)))["data"]
    result = (await client.put(f"/skills/{skill.id}/definition", headers=token(owner),
        json={"markdown": markdown, "expected_version": "1.0.0"})).json()
    assert result["status"] == "failure"
    await skill.refresh_from_db()
    assert skill.config["latest_build_id"] == first["build_id"] and skill.config["parser_revision"] == 0


@pytest.mark.asyncio
async def test_build_storage_is_discarded_when_sql_save_fails(setup, monkeypatch):
    client, owner, _, skill = setup
    original_save = Skill.save
    async def fail(self, *args, **kwargs):
        if self.config and self.config.get("latest_build_id"):
            raise OSError("simulated SQL write failure")
        return await original_save(self, *args, **kwargs)
    monkeypatch.setattr(Skill, "save", fail)
    result = await submit(client, owner, form(skill))
    assert result["status"] == "failure"
    await skill.refresh_from_db()
    assert skill.config is None
    assert not list(SkillPackageService().builder.root.glob("**/manifest.json"))


@pytest.mark.asyncio
async def test_real_knowledge_original_files_mount_into_full_skill_zip(kb_setup):
    client, owner, other, _, _ = kb_setup
    kb = (await save(client, owner)).json()["data"]
    skill = await Skill.create(name="实际知识库挂载", user_id=owner.id, is_enabled=False)
    basic = await submit(client, owner, form(skill), [])
    assert basic["status"] == "success"
    result = (await client.post(f"/knowledge-bases/{kb['id']}/mounts", headers=token(owner),
        json={"skill_ids": [skill.id], "resource_usage": "生成用例前先读取转账规则。"})).json()
    item = result["data"]["items"][0]
    assert item["status"] == "succeeded", result
    built = item["build"]
    assert built["version"] == "1.0.1" and built["source"]["knowledge_base_ids"] == [kb["id"]]
    download = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        reference = next(f for f in built["files"] if f["role"] == "reference")
        assert "余额必须充足" in archive.read(f"{built['name']}/{reference['path']}").decode()
    denied = await client.post(f"/knowledge-bases/{kb['id']}/mounts", headers=token(other),
        json={"skill_ids": [skill.id], "resource_usage": "尝试修改别人技能"})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_generic_crud_cannot_forge_or_reset_parser_version(setup):
    client, owner, _, skill = setup
    forged = await client.post("/skills/", headers=token(owner), json={"name": "伪造版本", "config": {"parser_revision": 999}})
    assert forged.status_code == 422
    built = (await submit(client, owner, form(skill)))["data"]
    reset = (await client.put(f"/skills/{skill.id}", headers=token(owner), json={"config": None})).json()
    assert reset["status"] == "success"
    await skill.refresh_from_db()
    assert skill.config["parser_revision"] == 0 and skill.config["latest_build_id"] == built["build_id"]
    name = (await client.put(f"/skills/{skill.id}", headers=token(owner), json={"name": "绕过表单修改"})).json()
    assert name["status"] == "failure"


@pytest.mark.asyncio
async def test_form_never_silently_uses_outdated_markdown_instead_of_new_instructions(setup):
    client, owner, _, skill = setup
    result = await submit(client, owner, form(skill, skill_markdown="旧执行指令正文"))
    assert result["status"] == "failure"
    assert result["data"]["errors"][0]["field"] == "skill_markdown"
