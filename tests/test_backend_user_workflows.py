"""从用户操作出发：失败重传、批量替换、文件改名、错误提示及权限。"""
import json
from pathlib import Path

import pytest

from applications.agent.models.agent_model import Skill
from applications.knowledge_base.models.knowledge_base_model import Document, DocumentChunk, KnowledgeBase
from configure import PROJECT_CONFIG
from enums import DocumentStatus
from test_platform_knowledge import FORM as KB_FORM, kb_setup, save
from test_skill_package_api import FORM as LEGACY_FORM, setup, token
from test_skill_developer_form import form, submit


@pytest.mark.asyncio
async def test_user_can_resubmit_the_same_file_after_processing_failure(kb_setup):
    client, owner, _, _, index = kb_setup
    index.fail = True
    kb = (await save(client, owner)).json()["data"]
    assert (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]["status"] == "failed"
    index.fail = False
    response = await save(client, owner, {**KB_FORM, "change_summary": "模型恢复后重新上传"}, kb_id=kb["id"])
    assert response.status_code == 200
    current = (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]
    assert current["status"] == "completed", "重新上传相同内容也应恢复失败文档，而不能悄悄跳过"
    assert current["document_count"] == 1 and index.rows


@pytest.mark.asyncio
async def test_duplicate_file_content_points_to_files_not_knowledge_name(kb_setup):
    client, owner, _, _, _ = kb_setup
    response = await save(client, owner, files=[("files", ("one.md", b"same rule")), ("files", ("two.md", b"same rule"))])
    assert response.status_code == 400
    errors = response.json()["data"]["errors"]
    assert errors[0]["field"].startswith("files"), "不能把附件内容重复提示成知识库名称有问题"
    assert "重复" in errors[0]["reason"] and "one.md" in errors[0]["reason"]
    assert await KnowledgeBase.all().count() == 0
    assert not list(PROJECT_CONFIG.upload_path.glob("*/*"))


@pytest.mark.asyncio
async def test_user_can_swap_two_documents_in_one_save(kb_setup):
    client, owner, _, _, _ = kb_setup
    kb = (await save(client, owner, files=[("files", ("a.md", b"rule A")), ("files", ("b.md", b"rule B"))])).json()["data"]
    response = await save(client, owner, {**KB_FORM, "change_summary": "批量替换两份文档"}, files=[
        ("files", ("a.md", b"rule B")), ("files", ("b.md", b"rule A"))], kb_id=kb["id"])
    assert response.status_code == 200, response.text
    docs = await Document.filter(knowledge_base_id=kb["id"], is_deleted=False)
    assert {d.filename: Path(d.file_path).read_bytes() for d in docs} == {"a.md": b"rule B", "b.md": b"rule A"}
    assert all(d.status == DocumentStatus.COMPLETED for d in docs)


@pytest.mark.asyncio
async def test_user_can_remove_a_file_and_upload_same_content_with_new_name(kb_setup):
    client, owner, _, _, _ = kb_setup
    kb = (await save(client, owner, files=[("files", ("old.md", b"the same business rule"))])).json()["data"]
    response = await save(client, owner, {**KB_FORM, "change_summary": "更正文档文件名", "retained_document_ids": []},
        files=[("files", ("new.md", b"the same business rule"))], kb_id=kb["id"])
    assert response.status_code == 200, response.text
    current = (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]
    assert [d["filename"] for d in current["documents"]] == ["new.md"]
    assert current["status"] == "completed" and not current["cleanup_pending"]


@pytest.mark.asyncio
async def test_polling_continues_while_other_documents_are_still_processing(kb_setup):
    client, owner, _, _, _ = kb_setup
    kb = (await save(client, owner, files=[("files", ("a.md", b"first")), ("files", ("b.md", b"second"))])).json()["data"]
    ids = [d["id"] for d in kb["documents"]]
    await Document.filter(id=ids[0]).update(status=DocumentStatus.FAILED)
    await Document.filter(id=ids[1]).update(status=DocumentStatus.PROCESSING)
    current = (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]
    assert current["status"] == "processing", "仍有文档处理时不应让页面提前停止轮询"
    assert current["documents"][0]["status"] == "failed"
    await Document.filter(id=ids[1]).update(status=DocumentStatus.COMPLETED)
    current = (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]
    assert current["status"] == "failed"


@pytest.mark.asyncio
async def test_blank_name_never_passes_name_availability_check(kb_setup):
    client, owner, _, _, _ = kb_setup
    response = await client.get("/knowledge-bases/name-availability", headers=token(owner), params={"name": " \t "})
    assert response.status_code == 400
    assert response.json()["data"]["errors"][0]["field"] == "knowledge_name"


@pytest.mark.asyncio
async def test_required_knowledge_field_has_chinese_actionable_message(kb_setup):
    client, owner, _, _, _ = kb_setup
    source = dict(KB_FORM)
    source.pop("description")
    response = await save(client, owner, source)
    assert response.status_code == 400
    error = response.json()["data"]["errors"][0]
    assert error["field"] == "description" and error["reason"] == "请填写知识库描述"


@pytest.mark.asyncio
async def test_skill_text_limit_message_names_the_field_and_limit(setup):
    client, owner, _, skill = setup
    result = await submit(client, owner, form(skill, description="长" * 1025))
    error = result["data"]["errors"][0]
    assert error["field"] == "description" and "描述" in error["reason"] and "1024" in error["reason"]


@pytest.mark.asyncio
async def test_old_upload_entry_also_rejects_empty_files(setup):
    client, owner, _, skill = setup
    source = {**LEGACY_FORM, "resources": [{"upload_index": 0, "role": "reference", "usage": "读取规则"}]}
    result = (await client.post(f"/skills/{skill.id}/builds/upload", headers=token(owner),
        data={"source": json.dumps(source)}, files=[("files", ("empty.md", b""))])).json()
    assert result["status"] == "failure" and "空" in result["data"]["errors"][0]["reason"]
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob("**/manifest.json"))


@pytest.mark.asyncio
async def test_stale_knowledge_save_preserves_current_files_and_history(kb_setup):
    client, owner, _, _, _ = kb_setup
    kb = (await save(client, owner)).json()["data"]
    await save(client, owner, {**KB_FORM, "change_summary": "先保存一次", "expected_version": "V1.0.0"}, files=[], kb_id=kb["id"])
    before = (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]
    response = await save(client, owner, {**KB_FORM, "change_summary": "旧窗口提交", "expected_version": "V1.0.0"},
        files=[("files", ("new.txt", b"unsaved change"))], kb_id=kb["id"])
    assert response.status_code == 409
    after = (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]
    assert before == after and len(list(PROJECT_CONFIG.upload_path.glob("*/*"))) == 1


@pytest.mark.asyncio
async def test_document_ids_cannot_be_mixed_between_knowledge_bases(kb_setup):
    client, owner, _, _, _ = kb_setup
    one = (await save(client, owner)).json()["data"]
    two = (await save(client, owner, {**KB_FORM, "knowledge_name": "第二个库"})).json()["data"]
    doc_id = two["documents"][0]["id"]
    for suffix in ["preview", "download"]:
        response = await client.get(f"/knowledge-bases/{one['id']}/documents/{doc_id}/{suffix}", headers=token(owner))
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_public_knowledge_can_be_mounted_to_readers_own_skill(kb_setup):
    client, owner, reader, _, _ = kb_setup
    kb = (await save(client, owner)).json()["data"]
    own = await Skill.create(name="读者自己的技能", user_id=reader.id, is_enabled=False)
    assert (await submit(client, reader, form(own)))["status"] == "success"
    response = await client.post(f"/knowledge-bases/{kb['id']}/mounts", headers=token(reader),
        json={"skill_ids": [own.id], "resource_usage": "生成前查看公开知识库"})
    assert response.json()["data"]["items"][0]["status"] == "succeeded"
    assert (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(reader))).json()["data"]["can_edit"] is False


@pytest.mark.asyncio
async def test_metadata_can_be_saved_while_documents_process(kb_setup):
    client, owner, _, _, index = kb_setup
    kb = (await save(client, owner)).json()["data"]
    await Document.filter(id=kb["documents"][0]["id"]).update(status=DocumentStatus.PROCESSING)
    calls = len(index.calls)
    result = await save(client, owner, {**KB_FORM, "description": "调整说明，不动处理中文件", "change_summary": "修改说明"},
        files=[], kb_id=kb["id"])
    assert result.status_code == 200 and result.json()["data"]["version"] == "V1.0.1"
    assert len(index.calls) == calls


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,field", [({"content": ""}, "content"), ({"change_summary": ""}, "change_summary")])
async def test_document_editor_validation_is_localized_and_preserves_saved_version(kb_setup, changes, field):
    client, owner, _, _, _ = kb_setup
    kb = (await save(client, owner)).json()["data"]
    doc = kb["documents"][0]
    response = await client.put(f"/knowledge-bases/{kb['id']}/documents/{doc['id']}/content", headers=token(owner),
        json={"content": "新内容", "change_summary": "修改规则", "expected_generation": 1, **changes})
    assert response.status_code == 422
    issue = response.json()["data"]["errors"][0]
    assert issue["field"] == field and issue["reason"].startswith("请填写")
    assert (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]["version"] == "V1.0.0"


@pytest.mark.asyncio
async def test_markdown_editor_empty_save_returns_field_error_without_losing_build(setup):
    client, owner, _, skill = setup
    built = (await submit(client, owner, form(skill)))["data"]
    response = await client.put(f"/skills/{skill.id}/definition", headers=token(owner),
        json={"markdown": " \n ", "expected_version": built["version"]})
    assert response.status_code == 422
    assert response.json()["data"]["errors"][0] == {"field": "markdown", "reason": "请填写Skill 定义"}
    current = (await client.get(f"/skills/{skill.id}/definition", headers=token(owner))).json()["data"]
    assert current["version"] == built["version"] and current["build"]["build_id"] == built["build_id"]


@pytest.mark.asyncio
async def test_parallel_skill_saves_cannot_create_duplicate_names_or_orphan_builds(setup):
    import asyncio
    client, owner, _, skill = setup
    another = await Skill.create(name="另一个实现", user_id=owner.id, is_enabled=False)
    results = await asyncio.gather(
        submit(client, owner, form(skill, skill_name="并发保存同一个名称")),
        submit(client, owner, form(another, skill_name="并发保存同一个名称")))
    assert sorted(result["status"] for result in results) == ["failure", "success"]
    assert await Skill.filter(name="并发保存同一个名称").count() == 1
    assert len(list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob("**/manifest.json"))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("file_state", ["missing", "corrupted"])
async def test_reupload_repairs_original_without_needless_reindex(kb_setup, file_state):
    client, owner, _, _, index = kb_setup
    kb = (await save(client, owner)).json()["data"]
    doc = await Document.get(id=kb["documents"][0]["id"])
    original = Path(doc.file_path).read_bytes()
    if file_state == "missing":
        Path(doc.file_path).unlink()
    else:
        Path(doc.file_path).write_bytes(b"corrupted storage")
    calls = len(index.calls)
    response = await save(client, owner, {**KB_FORM, "change_summary": "重新上传恢复原文件"}, kb_id=kb["id"])
    assert response.status_code == 200
    await doc.refresh_from_db()
    assert Path(doc.file_path).read_bytes() == original
    assert doc.status == DocumentStatus.COMPLETED and len(index.calls) == calls
