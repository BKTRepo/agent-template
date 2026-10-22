"""新表单完整接口链路，沿用旧接口的隔离数据库和认证测试夹具。"""
import io
import json
from pathlib import Path
import zipfile

from pydantic import ValidationError
import pytest
import yaml

from applications.agent.schemas.skill_package_schema import SkillDeveloperForm
from applications.agent.services.skill_upload_adapter import source_from_developer_form
from applications.agent.services.skill_package_builder import SkillPackageError
from applications.agent.services.skill_package_service import SkillPackageService
from configure import PROJECT_CONFIG
from test_skill_package_api import setup, token, document, FORM


def form(skill, **changes):
    return {"skill_id": skill.id, "skill_name": "八字段用例生成", "description": "按需求生成测试用例，适用于测试设计。",
            "skill_class_id": "SKILL-CASE-001", "instructions": "读取需求并生成用例。", **changes}


async def submit(client, owner, data, files=None):
    # 模拟新版表单逐项选择分类；负例显式传 [] 可测试未分类。
    if "resource_categories" not in data and files:
        from applications.agent.services.skill_resource_rules import resource_role
        categories = []
        for _, (filename, *_) in files:
            try:
                categories.append(resource_role(filename))
            except ValueError:
                categories.append("reference")
        data = {**data, "resource_categories": categories}
    return (await client.post("/skills/form/builds", headers=token(owner),
                             data={"source": json.dumps(data)}, files=files or [])).json()


def test_adapter_preserves_description_version_without_client_metadata():
    dto = SkillDeveloperForm(skill_id="s-1", skill_name=" 中文名称 ", description=' 描述: "原文"\n第二段。 ',
                             version=" v0.2.0 ", skill_class_id="SKILL-CASE-001", instructions=" 首个段落。\n第二段。 ")
    built = source_from_developer_form(dto, [])
    assert built.name.startswith("skill-") and len(built.name) <= 64
    assert built.display_name == "中文名称" and built.version == "1.0.0"
    assert built.description == '描述: "原文"\n第二段。'
    assert built.instructions == "首个段落。\n第二段。"
    assert built.description == source_from_developer_form(dto, []).description
    assert built.name == source_from_developer_form(dto, []).name
    assert built.system is None and built.team is None and built.skill_class_id == "SKILL-CASE-001"
    long = dto.model_copy(update={"instructions": "长" * 5000})
    assert source_from_developer_form(long, []).description == built.description
    for field in ("creator_id", "maintainer_id", "technical_name", "role", "target_path"):
        with pytest.raises(ValidationError):
            SkillDeveloperForm(**dto.model_dump(), **{field: "client-value"})


def test_adapter_accepts_all_applications():
    dto = SkillDeveloperForm(skill_id="s-all", skill_name="全应用测试用例生成", description="面向全应用生成测试用例。",
                             version="1.0.0", skill_class_id="SKILL-CASE-001", application="*", instructions="读取需求并生成用例。")
    assert source_from_developer_form(dto, []).application == "*"


@pytest.mark.parametrize("knowledge,files", [(False, ["rule.md"]), (True, [])])
def test_common_usage_is_required_for_either_kind_of_resource(knowledge, files):
    dto = SkillDeveloperForm(skill_id="s-1", skill_name="名称", description="描述", version="0.2.0",
                             instructions="步骤", skill_class_id="SKILL-CASE-001", resource_categories=["reference"] if files else [],
                             knowledge_base_ids=["kb"] if knowledge else [])
    with pytest.raises(SkillPackageError) as error:
        source_from_developer_form(dto, files)
    assert [issue.field for issue in error.value.report.missing_fields] == ["resource_usage"]


@pytest.mark.asyncio
async def test_new_route_plain_form_and_stable_edit(setup):
    client, owner, _, skill = setup
    description = '场景: "测试设计"\n保留  内部空白与换行。'
    result = await submit(client, owner, form(skill, description=description, version="v0.2.0"))
    assert result["status"] == "success", result
    built = result["data"]
    assert len(built["files"]) == 1
    original_bytes = Path(built["skill_directory"]).joinpath("SKILL.md").read_bytes()
    raw = Path(built["skill_directory"]).joinpath("SKILL.md").read_text(encoding="utf-8")
    header = yaml.safe_load(raw.split("---\n", 2)[1])
    assert header["metadata"]["creator_id"] == str(owner.id)
    assert header["description"] == description
    assert header["metadata"]["version"] == built["version"] == "1.0.0"
    assert built["source"]["description"] == description
    assert "compatibility" not in header and "## 资源使用说明" not in raw
    assert built["source"]["instructions"] == "读取需求并生成用例。"
    assert built["source"]["resource_usage"] == ""
    again = await submit(client, owner, form(skill, skill_name="改后的中文名称", description="新版描述",
                                           version="v0.3.0", compatibility="Python 3.12"))
    assert again["status"] == "success"
    assert again["data"]["name"] == built["name"]
    assert again["data"]["build_id"] != built["build_id"]
    assert again["data"]["version"] == again["data"]["source"]["version"] == "1.0.1"
    assert again["data"]["source"]["description"] == "新版描述"
    await skill.refresh_from_db()
    assert skill.name == "改后的中文名称" and skill.description == "新版描述" and not skill.is_enabled
    old = (await client.get(f"/skills/{skill.id}/builds/{built['build_id']}", headers=token(owner))).json()
    assert old["status"] == "success"
    assert old["data"]["source"]["description"] == description
    assert old["data"]["source"]["version"] == "1.0.0"
    repeated = await submit(client, owner, form(skill, version="v0.3.0"))
    assert repeated["status"] == "success"
    assert repeated["data"]["build_id"] not in {built["build_id"], again["data"]["build_id"]}
    assert repeated["data"]["name"] == built["name"]
    history = (await client.get(f"/skills/{skill.id}/builds", headers=token(owner))).json()["data"]
    assert history["total"] == 3
    download = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.read(f"{built['name']}/SKILL.md") == original_bytes


@pytest.mark.asyncio
async def test_unified_mixed_upload_preserves_bytes_and_common_usage_once(setup):
    client, owner, _, skill = setup
    usage = "rules.md 核对规则；check.py 校验输入；dependencies.zip 提供依赖。"
    data = form(skill, resource_usage=usage, compatibility="Python 3.12；预先提供依赖")
    uploads = [("files", ("rules.md", b"rules", "text/markdown")),
               ("files", ("check.py", b"raise RuntimeError('must not run')", "text/plain")),
               ("files", ("dependencies.zip", b"archive-bytes-no-extraction", "application/zip"))]
    result = await submit(client, owner, data, uploads)
    assert result["status"] == "success", result
    built = result["data"]
    assert {entry["path"] for entry in built["files"]} == {"SKILL.md", "references/rules.md", "scripts/check.py", "assets/dependencies.zip"}
    raw = Path(built["skill_directory"]).joinpath("SKILL.md").read_text(encoding="utf-8")
    assert raw.count(usage) == 1
    assert built["source"]["instructions"] == data["instructions"]
    assert built["source"]["resource_usage"] == usage
    downloaded = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert archive.read(f"{built['name']}/scripts/check.py") == uploads[1][1][1]
        assert archive.read(f"{built['name']}/assets/dependencies.zip") == uploads[2][1][1]


@pytest.mark.asyncio
async def test_form_authentication_and_ownership(setup):
    client, owner, other, skill = setup
    data = {"source": json.dumps(form(skill))}
    assert (await client.post("/skills/form/builds", headers={"token": "bad"}, data=data)).status_code == 401
    assert (await client.post("/skills/form/builds", data=data)).status_code == 422
    denied = await submit(client, other, form(skill))
    assert denied["status"] == "failure" and denied["message"] == "技能不存在"
    assert not Path(PROJECT_CONFIG.SKILL_BUILD_DIR).exists()


@pytest.mark.asyncio
async def test_missing_fields_and_client_identity_rejected(setup):
    client, owner, _, skill = setup
    missing = await submit(client, owner, {"skill_id": skill.id})
    assert {issue["field"] for issue in missing["data"]["missing_fields"]} == {"skill_name", "description", "skill_class_id", "instructions"}
    no_id = await submit(client, owner, {"skill_name": "名字", "instructions": "步骤"})
    assert no_id["data"]["missing_fields"][0]["field"] == "skill_id"
    identity = await submit(client, owner, form(skill, creator_id="other"))
    assert identity["status"] == "failure" and identity["data"]["errors"][0]["field"] == "creator_id"
    no_usage = await submit(client, owner, form(skill), [("files", ("r.md", b"r", "text/markdown"))])
    assert no_usage["data"]["missing_fields"][0]["field"] == "resource_usage"
    unknown = await submit(client, owner, form(skill, resource_usage="说明"), [("reference_files", ("r.md", b"r", "text/markdown"))])
    assert unknown["status"] == "failure" and unknown["data"]["errors"][0]["field"] == "reference_files"
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob("**/manifest.json"))


@pytest.mark.asyncio
async def test_knowledge_usage_permissions_and_snapshot(setup):
    client, owner, other, skill = setup
    kb, _ = await document(owner)
    missing = await submit(client, owner, form(skill, knowledge_base_ids=[kb.id]))
    assert missing["data"]["missing_fields"][0]["field"] == "resource_usage"
    private, _ = await document(other)
    denied = await submit(client, owner, form(skill, knowledge_base_ids=[private.id], resource_usage="读取规则"))
    assert denied["status"] == "failure"
    good = await submit(client, owner, form(skill, knowledge_base_ids=[kb.id, kb.id], resource_usage="读取规则"))
    assert good["status"] == "success" and len(good["data"]["files"]) == 2
    assert good["data"]["files"][1]["usage"] == "读取规则"
    assert good["data"]["source"]["knowledge_base_ids"] == [kb.id]


@pytest.mark.asyncio
async def test_adapting_existing_skill_preserves_legacy_technical_name(setup):
    client, owner, _, skill = setup
    old = (await client.post(f"/skills/{skill.id}/builds", headers=token(owner), json=FORM)).json()
    new = await submit(client, owner, form(skill))
    assert old["status"] == new["status"] == "success"
    assert new["data"]["name"] == old["data"]["name"] == "case-generator"
    assert new["data"]["version"] == "1.0.0" and old["data"]["version"] == "0.1.0"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["description", "skill_class_id"])
@pytest.mark.parametrize("value", [None, "", " \n\t ", "omitted"])
async def test_new_required_fields_never_fall_back_to_history(setup, field, value):
    client, owner, _, skill = setup
    old = await submit(client, owner, form(skill))
    assert old["status"] == "success"
    data = form(skill, skill_name="无效修改")
    if value == "omitted":
        data.pop(field)
    else:
        data[field] = value
    result = await submit(client, owner, data)
    assert result["status"] == "failure"
    issues = result["data"].get("missing_fields", []) + result["data"].get("errors", [])
    assert any(issue["field"] == field for issue in issues)
    await skill.refresh_from_db()
    assert skill.name == "八字段用例生成" and skill.description == form(skill)["description"]
    history = (await client.get(f"/skills/{skill.id}/builds", headers=token(owner))).json()["data"]
    assert history["total"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field,limit", [("description", 1024), ("compatibility", 500)])
async def test_text_limits_are_rejected_without_truncation(setup, field, limit):
    client, owner, _, skill = setup
    original_name, original_description = skill.name, skill.description
    invalid = await submit(client, owner, form(skill, **{field: "长" * (limit + 1)}))
    assert invalid["status"] == "failure" and invalid["data"]["errors"][0]["field"] == field
    await skill.refresh_from_db()
    assert (skill.name, skill.description) == (original_name, original_description)
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob("**/manifest.json"))
    text = "长" * limit
    valid = await submit(client, owner, form(skill, **{field: text}))
    assert valid["status"] == "success", valid
    assert valid["data"]["source"][field] == text


@pytest.mark.asyncio
@pytest.mark.parametrize("with_files", [False, True])
async def test_empty_knowledge_ids_never_access_knowledge_base(setup, monkeypatch, with_files):
    client, owner, _, skill = setup

    async def forbidden_knowledge_access(*args, **kwargs):
        raise AssertionError("不挂载知识库时不应查询知识库")

    monkeypatch.setattr(SkillPackageService, "_knowledge_base", forbidden_knowledge_access)
    files = [("files", ("rules.md", b"rules", "text/markdown")),
             ("files", ("flow.png", b"image-bytes", "image/png")),
             ("files", ("check.py", b"raise RuntimeError('do not run')", "text/plain"))] if with_files else []
    result = await submit(client, owner, form(skill, knowledge_base_ids=[], resource_usage="读取规则和图片，脚本供运行端使用" if files else ""), files)
    assert result["status"] == "success", result
    built = result["data"]
    expected = {"SKILL.md", "references/rules.md", "assets/flow.png", "scripts/check.py"} if files else {"SKILL.md"}
    assert {row["path"] for row in built["files"]} == expected
    assert built["source"]["knowledge_base_ids"] == []
    queried = (await client.get(f"/skills/{skill.id}/builds/{built['build_id']}", headers=token(owner))).json()
    assert queried["status"] == "success" and queried["data"]["files"] == built["files"]
    response = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {f"{built['name']}/{name}" for name in expected}
