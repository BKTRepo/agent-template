from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import zipfile

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import jwt
import pytest
import pytest_asyncio
import yaml

from applications.wrq.agent.models.agent_model import Skill
from applications.wrq.agent.views import skills_router
from applications.wrq.knowledge_base.models.knowledge_base_model import Document, KnowledgeBase
from applications.user.models.user_model import User
from configure import PROJECT_CONFIG


FORM = {"name": "case-generator", "display_name": "核心系统用例生成", "description": "按需求生成测试用例，适用于测试设计。",
        "instructions": "读取需求后生成正向、边界和异常用例。", "version": "0.1.0"}


def token(user):
    return {"token": jwt.encode({"user_id": user.id, "token_version": user.token_version,
                                "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                               PROJECT_CONFIG.AUTH_SECRET_KEY, algorithm="HS256")}


@pytest_asyncio.fixture
async def setup(database, tmp_path, monkeypatch):
    monkeypatch.setattr(PROJECT_CONFIG, "SKILL_BUILD_DIR", str(tmp_path / "builds"))
    monkeypatch.setattr(PROJECT_CONFIG, "OUTPUT_UPLOAD_DIR", str(tmp_path / "uploads"))
    Path(PROJECT_CONFIG.OUTPUT_UPLOAD_DIR).mkdir()
    owner = await User.create(username="owner", alias="owner", email="owner@example.com", password="unused")
    other = await User.create(username="other", alias="other", email="other@example.com", password="unused")
    skill = await Skill.create(name="核心用例生成", user_id=owner.id, is_enabled=False)
    app = FastAPI()
    app.include_router(skills_router, prefix="/skills")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, owner, other, skill


async def document(owner, *, public=False, outside=False):
    kb = await KnowledgeBase.create(user_id=owner.id, knowledge_name="业务知识库", is_public=public)
    root = PROJECT_CONFIG.upload_path.parent if outside else PROJECT_CONFIG.upload_path
    path = root / f"{kb.id}.md"
    content = "转账规则：金额必须大于零。".encode()
    path.write_bytes(content)
    doc = await Document.create(knowledge_base_id=kb.id, filename="规则.md", file_path=str(path),
                                file_size=len(content), content_hash=hashlib.sha256(content).hexdigest())
    return kb, doc


@pytest.mark.asyncio
async def test_authenticated_upload_build_read_and_download(setup):
    client, owner, _, skill = setup
    form = {**FORM, "compatibility": "Python 3.11+；无需网络访问。",
            "resources": [{"upload_index": 0, "role": "reference", "usage": "生成前读取业务规则。"},
                                 {"upload_index": 1, "role": "asset", "target_path": "templates/output.json",
                                  "usage": "按此模板组织输出。"}]}
    response = await client.post(f"/skills/{skill.id}/builds/upload", headers=token(owner),
                                data={"source": json.dumps(form)},
                                files=[("files", ("业务规则.md", b"rules", "text/markdown")),
                                       ("files", ("template.json", b'{"cases": []}', "application/json"))])
    assert response.json()["status"] == "success", response.text
    built = response.json()["data"]
    assert Path(built["skill_directory"]).joinpath("SKILL.md").exists()
    raw = Path(built["skill_directory"]).joinpath("SKILL.md").read_text(encoding="utf-8")
    header = yaml.safe_load(raw.split("---\n", 2)[1])
    assert header["compatibility"] == form["compatibility"]
    assert header["metadata"]["creator_id"] == str(owner.id)
    assert "生成前读取业务规则。" in raw and "按此模板组织输出。" in raw
    assert (await client.get(f"/skills/{skill.id}/builds/{built['build_id']}", headers=token(owner))).json()["status"] == "success"
    download = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
    assert download.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.read("case-generator/assets/templates/output.json") == b'{"cases": []}'
    await skill.refresh_from_db()
    assert not skill.is_enabled
    assert not list((Path(PROJECT_CONFIG.SKILL_BUILD_DIR) / ".uploads").iterdir())


@pytest.mark.asyncio
async def test_missing_information_is_field_level_report(setup):
    client, owner, _, skill = setup
    report = (await client.post(f"/skills/{skill.id}/validate", headers=token(owner), json={})).json()["data"]
    assert not report["valid"]
    assert {e["field"] for e in report["missing_fields"]} == {"name", "display_name", "description", "instructions", "version"}
    result = (await client.post(f"/skills/{skill.id}/builds", headers=token(owner), json={})).json()
    assert result["status"] == "failure"
    assert not Path(PROJECT_CONFIG.SKILL_BUILD_DIR).exists()


@pytest.mark.asyncio
async def test_other_users_cannot_build_read_or_download(setup):
    client, owner, other, skill = setup
    built = (await client.post(f"/skills/{skill.id}/builds", headers=token(owner), json=FORM)).json()["data"]
    for method, path in [("POST", f"/skills/{skill.id}/builds"),
                         ("GET", f"/skills/{skill.id}/builds/{built['build_id']}"),
                         ("GET", f"/skills/{skill.id}/builds/{built['build_id']}/download")]:
        kwargs = {"json": FORM} if method == "POST" else {}
        result = await client.request(method, path, headers=token(other), **kwargs)
        assert result.json()["status"] == "failure"
        assert result.json()["message"] == "技能不存在"


@pytest.mark.asyncio
async def test_invalid_token_and_missing_header_rejected(setup):
    client, _, _, skill = setup
    assert (await client.post(f"/skills/{skill.id}/validate", headers={"token": "invalid"}, json=FORM)).status_code == 401
    assert (await client.post(f"/skills/{skill.id}/validate", json=FORM)).status_code == 422


@pytest.mark.asyncio
async def test_private_and_public_knowledge_base_permissions(setup):
    client, owner, other, skill = setup
    _, private = await document(other)
    _, public = await document(other, public=True)
    form = {**FORM, "resources": [{"document_id": private.id, "role": "reference"}]}
    denied = (await client.post(f"/skills/{skill.id}/builds", headers=token(owner), json=form)).json()
    assert denied["status"] == "failure"
    form["resources"][0]["document_id"] = public.id
    allowed = (await client.post(f"/skills/{skill.id}/builds", headers=token(owner), json=form)).json()
    assert allowed["status"] == "success"
    assert allowed["data"]["files"][1]["document_id"] == public.id


@pytest.mark.asyncio
async def test_knowledge_base_snapshot_and_resource_deduplication(setup):
    client, owner, _, skill = setup
    kb, doc = await document(owner)
    form = {**FORM, "knowledge_base_ids": [kb.id, kb.id]}
    built = (await client.post(f"/skills/{skill.id}/builds", headers=token(owner), json=form)).json()["data"]
    assert len(built["files"]) == 2
    prefix = hashlib.sha256(doc.id.encode()).hexdigest()[:12]
    assert built["files"][1]["path"] == f"references/{prefix}-规则.md"
    form["resources"] = [{"document_id": doc.id, "role": "reference"}]
    built = (await client.post(f"/skills/{skill.id}/builds", headers=token(owner), json=form)).json()["data"]
    assert len(built["files"]) == 2


@pytest.mark.asyncio
async def test_resource_outside_upload_directory_cannot_be_copied(setup):
    client, owner, _, skill = setup
    _, doc = await document(owner, outside=True)
    form = {**FORM, "resources": [{"document_id": doc.id, "role": "reference"}]}
    result = (await client.post(f"/skills/{skill.id}/builds", headers=token(owner), json=form)).json()
    assert result["status"] == "failure"
    assert "上传目录之外" in result["data"]["errors"][0]["reason"]


@pytest.mark.asyncio
async def test_pinned_hash_and_original_content_changes_rejected(setup):
    client, owner, _, skill = setup
    _, doc = await document(owner)
    form = {**FORM, "resources": [{"document_id": doc.id, "role": "reference", "content_hash": "0" * 64}]}
    assert (await client.post(f"/skills/{skill.id}/builds", headers=token(owner), json=form)).json()["status"] == "failure"
    form["resources"][0]["content_hash"] = doc.content_hash
    Path(doc.file_path).write_bytes(b"changed")
    result = (await client.post(f"/skills/{skill.id}/builds", headers=token(owner), json=form)).json()
    assert result["status"] == "failure"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["missing", "unbound", "bad-json", "traversal", "size"])
async def test_upload_errors_and_temporary_file_cleanup(setup, monkeypatch, reason):
    client, owner, _, skill = setup
    form = {**FORM, "resources": [{"upload_index": 0, "role": "reference", "usage": "生成前读取规则。"}]}
    files = [("files", ("rules.md", b"rules"))]
    if reason == "missing":
        files = []
    if reason == "unbound":
        form["resources"] = []
    if reason == "traversal":
        form["resources"][0]["target_path"] = "../../escape"
    if reason == "size":
        monkeypatch.setattr(PROJECT_CONFIG, "SKILL_RESOURCE_MAX_BYTES", 2)
    result = await client.post(f"/skills/{skill.id}/builds/upload", headers=token(owner),
                              data={"source": "invalid" if reason == "bad-json" else json.dumps(form)}, files=files)
    assert result.json()["status"] == "failure", result.text
    root = Path(PROJECT_CONFIG.SKILL_BUILD_DIR)
    assert not list(root.glob("**/manifest.json"))
    assert not list(root.glob(".uploads/*"))


@pytest.mark.asyncio
async def test_existing_skill_routes_are_preserved(setup):
    client, owner, _, skill = setup
    result = await client.get(f"/skills/{skill.id}", headers=token(owner))
    assert result.json()["data"]["id"] == skill.id
    result = await client.get("/skills/", headers=token(owner), params={"manage": "true"})
    assert result.json()["total"] == 1


@pytest.mark.asyncio
async def test_build_history_can_be_reloaded_and_is_scoped_to_owner(setup):
    client, owner, other, skill = setup
    url = f"/skills/{skill.id}/builds"
    empty = (await client.get(url, headers=token(owner))).json()["data"]
    assert empty == {"items": [], "total": 0}
    first = (await client.post(url, headers=token(owner), json=FORM)).json()["data"]
    second = (await client.post(url, headers=token(owner), json={**FORM, "version": "0.2.0"})).json()["data"]
    history = (await client.get(url, headers=token(owner), params={"limit": 1})).json()["data"]
    assert history["total"] == 2
    assert history["items"][0]["build_id"] == second["build_id"]
    older = (await client.get(url, headers=token(owner), params={"limit": 1, "offset": 1})).json()["data"]
    assert older["items"][0]["build_id"] == first["build_id"]
    assert (await client.get(url, headers=token(other))).json()["status"] == "failure"


@pytest.mark.asyncio
async def test_missing_upload_usage_reports_field_without_publishing(setup):
    client, owner, _, skill = setup
    form = {**FORM, "resources": [{"upload_index": 0, "role": "reference"}]}
    report = (await client.post(f"/skills/{skill.id}/validate", headers=token(owner), json=form)).json()["data"]
    assert not report["valid"]
    assert {issue["field"] for issue in report["missing_fields"]} == {"resources[0].usage"}
    result = (await client.post(f"/skills/{skill.id}/builds/upload", headers=token(owner),
                               data={"source": json.dumps(form)},
                               files=[("files", ("rules.md", b"rules", "text/markdown"))])).json()
    assert result["status"] == "failure"
    assert {issue["field"] for issue in result["data"]["missing_fields"]} == {"resources[0].usage"}
    assert not Path(PROJECT_CONFIG.SKILL_BUILD_DIR).exists()


@pytest.mark.asyncio
async def test_entry_uploads_preserve_scripts_structure_and_do_not_execute(setup, tmp_path):
    client, owner, _, skill = setup
    marker = tmp_path / "script-executed"
    main = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n".encode()
    helper = b"def check(value):\n    return bool(value)\n"
    rules = "演示规则：金额必须大于零。".encode()
    form = {**FORM, "compatibility": "运行脚本时需要 Python 3.12+。",
            "reference_uploads": [{"usage": "生成前读取规则。"}],
            "script_uploads": [{"usage": "检查时调用 python scripts/main.py input.json。"},
                               {"usage": "供主脚本导入使用。", "target_path": "utils/helpers.py"}]}
    # multipart 跨入口的发送顺序不影响各入口独立的文件序号。
    response = await client.post(f"/skills/{skill.id}/builds/upload/entries", headers=token(owner),
                                 data={"source": json.dumps(form)},
                                 files=[("script_files", ("main.py", main)),
                                        ("reference_files", ("business-rules.md", rules)),
                                        ("script_files", ("helpers.py", helper))])
    assert response.json()["status"] == "success", response.text
    built = response.json()["data"]
    root = Path(built["skill_directory"])
    assert (root / "scripts/main.py").read_bytes() == main
    assert (root / "scripts/utils/helpers.py").read_bytes() == helper
    assert (root / "references/business-rules.md").read_bytes() == rules
    assert not marker.exists()
    raw = (root / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/utils/helpers.py" in raw and "python scripts/main.py input.json" in raw
    assert yaml.safe_load(raw.split("---\n", 2)[1])["compatibility"] == form["compatibility"]
    assert [item["role"] for item in built["source"]["resources"]] == ["reference", "script", "script"]
    read = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}", headers=token(owner))
    assert read.json()["status"] == "success"
    downloaded = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert archive.read("case-generator/scripts/utils/helpers.py") == helper
    assert not marker.exists()
    assert not list((Path(PROJECT_CONFIG.SKILL_BUILD_DIR) / ".uploads").iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("entry,folder", [("reference", "references"), ("script", "scripts")])
async def test_single_entry_uploads_use_entry_instead_of_file_extension(setup, entry, folder):
    client, owner, _, skill = setup
    form = {**FORM, f"{entry}_uploads": [{"usage": "按需使用这个文件。"}]}
    response = await client.post(f"/skills/{skill.id}/builds/upload/entries", headers=token(owner),
                                 data={"source": json.dumps(form)},
                                 files=[(f"{entry}_files", ("file.py", b"print('example')\n"))])
    assert response.json()["status"] == "success", response.text
    root = Path(response.json()["data"]["skill_directory"])
    assert (root / folder / "file.py").is_file()
    assert not (root / ("scripts" if folder == "references" else "references")).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,field", [
    ("usage", "script_uploads[0].usage"), ("missing-file", "script_uploads"),
    ("missing-spec", "script_uploads"), ("traversal", "script_uploads[0].target_path"),
    ("conflict", "script_uploads[1]"), ("size", "script_files[0]"),
    ("hash", "script_uploads[0]"), ("unknown-entry", "files"),
])
async def test_script_entry_upload_errors_are_actionable_and_cleaned(setup, monkeypatch, reason, field):
    client, owner, _, skill = setup
    form = {**FORM, "script_uploads": [{"usage": "运行 python scripts/check.py。"}]}
    files = [("script_files", ("check.py", b"print('example')\n"))]
    if reason == "usage":
        form["script_uploads"][0]["usage"] = " \n "
    elif reason == "missing-file":
        files = []
    elif reason == "missing-spec":
        form["script_uploads"] = []
    elif reason == "traversal":
        form["script_uploads"][0]["target_path"] = "../outside.py"
    elif reason == "conflict":
        form["script_uploads"].append({"usage": "补充脚本。", "target_path": "CHECK.py"})
        files.append(("script_files", ("other.py", b"pass\n")))
    elif reason == "size":
        monkeypatch.setattr(PROJECT_CONFIG, "SKILL_RESOURCE_MAX_BYTES", 2)
    elif reason == "hash":
        form["script_uploads"][0]["content_hash"] = "0" * 64
    elif reason == "unknown-entry":
        files = [("files", ("check.py", b"pass\n"))]
    result = (await client.post(f"/skills/{skill.id}/builds/upload/entries", headers=token(owner),
                               data={"source": json.dumps(form)}, files=files)).json()
    assert result["status"] == "failure", result
    issues = result["data"]["missing_fields"] + result["data"]["errors"]
    assert field in {issue["field"] for issue in issues}
    root = Path(PROJECT_CONFIG.SKILL_BUILD_DIR)
    assert not list(root.glob("**/manifest.json"))
    assert not list(root.glob("**/.building-*"))
    assert not list(root.glob(".uploads/*"))


@pytest.mark.asyncio
async def test_entry_endpoint_keeps_authentication_and_skill_ownership(setup):
    client, owner, other, skill = setup
    url = f"/skills/{skill.id}/builds/upload/entries"
    form = {**FORM, "script_uploads": [{"usage": "运行脚本。"}]}
    files = [("script_files", ("check.py", b"pass\n"))]
    assert (await client.post(url, data={"source": json.dumps(form)}, files=files)).status_code == 422
    assert (await client.post(url, headers={"token": "invalid"}, data={"source": json.dumps(form)}, files=files)).status_code == 401
    result = (await client.post(url, headers=token(other), data={"source": json.dumps(form)}, files=files)).json()
    assert result["status"] == "failure" and result["message"] == "技能不存在"
    assert not Path(PROJECT_CONFIG.SKILL_BUILD_DIR).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_source", ["invalid-json", json.dumps({**FORM, "script_uploads": [{"role": "asset", "usage": "运行。"}]})])
async def test_entry_endpoint_rejects_invalid_json_and_client_role_override(setup, bad_source):
    client, owner, _, skill = setup
    result = (await client.post(f"/skills/{skill.id}/builds/upload/entries", headers=token(owner),
                               data={"source": bad_source}, files=[("script_files", ("check.py", b"pass\n"))])).json()
    assert result["status"] == "failure"
    assert result["data"]["errors"]
    assert not Path(PROJECT_CONFIG.SKILL_BUILD_DIR).exists()
