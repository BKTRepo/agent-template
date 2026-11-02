"""用户边界与故障注入：删除恢复、异步竞争、外部返回、上传及构建保护。"""
import asyncio
from pathlib import Path

import pytest

from applications.knowledge_base.models.knowledge_base_model import Document, DocumentChunk
from applications.knowledge_base.schemas.platform_schema import KnowledgeForm
from applications.knowledge_base.services.document_pipeline import DocumentPipeline
from applications.knowledge_base.services.platform_service import KnowledgeError
from configure import PROJECT_CONFIG
from enums import DocumentStatus
from test_platform_knowledge import FORM, kb_setup, save
from test_skill_package_api import setup, token
from test_skill_developer_form import form, submit


async def two_documents(client, owner):
    kb = (await save(client, owner, files=[("files", ("keep.md", b"keep rule")),
        ("files", ("remove.md", b"remove rule"))])).json()["data"]
    docs = await Document.filter(knowledge_base_id=kb["id"])
    return kb, next(d for d in docs if d.filename == "keep.md"), next(d for d in docs if d.filename == "remove.md")


async def remove(client, owner, kb, keep):
    return await save(client, owner, {**FORM, "change_summary": "移除附件", "retained_document_ids": [keep.id]},
                      files=[], kb_id=kb["id"])


@pytest.mark.asyncio
async def test_delete_file_in_use_retains_record_and_exposes_retry(kb_setup, monkeypatch):
    client, owner, _, _, _ = kb_setup
    kb, keep, target = await two_documents(client, owner)
    unlink = Path.unlink
    def busy(path, *args, **kwargs):
        if path == Path(target.file_path):
            raise PermissionError("file in use")
        return unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", busy)
        assert (await remove(client, owner, kb, keep)).status_code == 200
    row = await Document.get_or_none(id=target.id)
    assert row is not None, "磁盘清理失败时不能删除用于重试的数据库记录"
    assert row.is_deleted and row.status == DocumentStatus.DELETE_FAILED
    detail = (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]
    task = next(t for t in detail["cleanup_tasks"] if t["document_id"] == target.id)
    assert task["status"] == "delete_failed" and task["can_retry"] and task["error_message"]
    retry = await client.post(f"/knowledge-bases/{kb['id']}/documents/{target.id}/retry", headers=token(owner))
    assert retry.status_code == 200
    assert not await Document.filter(id=target.id).exists() and not Path(target.file_path).exists()


@pytest.mark.asyncio
async def test_delete_vector_failure_preserves_file_and_does_not_block_other_document(kb_setup, monkeypatch):
    client, owner, _, _, index = kb_setup
    kb, keep, target = await two_documents(client, owner)
    async def offline(ids):
        raise ConnectionError("vector service down")
    with monkeypatch.context() as patch:
        patch.setattr(index, "remove", offline)
        assert (await remove(client, owner, kb, keep)).status_code == 200
    target_row = await Document.get(id=target.id)
    assert target_row.status == DocumentStatus.DELETE_FAILED and Path(target.file_path).exists()
    await keep.refresh_from_db()
    assert keep.status == DocumentStatus.COMPLETED
    assert await DocumentChunk.filter(document_id=target.id).exists()
    assert (await client.post(f"/knowledge-bases/{kb['id']}/retry", headers=token(owner))).status_code == 200
    assert not await Document.filter(id=target.id).exists()
    assert set(index.rows) == set(await DocumentChunk.all().values_list("chroma_id", flat=True))


@pytest.mark.asyncio
@pytest.mark.parametrize("outside", [False, True])
async def test_delete_missing_file_is_idempotent_but_outside_path_is_not_success(kb_setup, tmp_path, outside):
    client, owner, _, service, _ = kb_setup
    kb, keep, target = await two_documents(client, owner)
    Path(target.file_path).unlink()
    if outside:
        external = tmp_path / "external.md"
        external.write_text("must preserve", encoding="utf-8")
        target.file_path = str(external)
        await target.save()
    await remove(client, owner, kb, keep)
    if outside:
        row = await Document.get_or_none(id=target.id)
        assert row is not None and row.status == DocumentStatus.DELETE_FAILED
        assert external.read_text(encoding="utf-8") == "must preserve"
    else:
        assert not await Document.filter(id=target.id).exists()
        await service.process(target.id)  # 重复回调应安静结束。


@pytest.mark.asyncio
@pytest.mark.parametrize("doc_id", ["unknown", "other-base"])
async def test_retry_unknown_or_cross_base_document_returns_not_found(kb_setup, doc_id):
    client, owner, _, _, _ = kb_setup
    one = (await save(client, owner)).json()["data"]
    if doc_id == "other-base":
        two = (await save(client, owner, {**FORM, "knowledge_name": "另一个知识库"})).json()["data"]
        doc_id = two["documents"][0]["id"]
    response = await client.post(f"/knowledge-bases/{one['id']}/documents/{doc_id}/retry", headers=token(owner))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_raw_parse_callback_cannot_resurrect_deleted_document(kb_setup):
    client, owner, _, service, index = kb_setup
    _, _, target = await two_documents(client, owner)
    await Document.filter(id=target.id).update(is_deleted=True, status=DocumentStatus.PROCESSING, processing_started_time=None)
    calls = len(index.calls)
    await service.pipeline.process(target.id)
    await target.refresh_from_db()
    assert target.is_deleted and len(index.calls) == calls, "已移除文档不能被旧解析回调再次向量化"


@pytest.mark.asyncio
@pytest.mark.parametrize("pause_at", ["embed", "put"])
async def test_remove_processing_document_fences_late_worker_and_leaves_no_vectors(kb_setup, monkeypatch, pause_at):
    client, owner, _, service, index = kb_setup
    kb, keep, target = await two_documents(client, owner)
    await Document.filter(id=target.id).update(status=DocumentStatus.PROCESSING, processing_started_time=None,
                                             generation=target.generation + 1)
    entered, release = asyncio.Event(), asyncio.Event()
    original = getattr(index, pause_at)
    async def paused(*args):
        entered.set()
        await release.wait()
        return await original(*args)
    monkeypatch.setattr(index, pause_at, paused)
    worker = asyncio.create_task(service.process(target.id))
    deletion = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        _, jobs = await service.save(owner, KnowledgeForm(**{**FORM, "change_summary": "移除处理中文档",
            "retained_document_ids": [keep.id]}), [], kb_id=kb["id"])
        assert target.id in jobs
        deletion = asyncio.create_task(service.process(target.id))
    finally:
        release.set()
        await asyncio.wait_for(worker, 5)
        if deletion:
            await asyncio.wait_for(deletion, 5)
    assert not await Document.filter(id=target.id).exists()
    assert not any(row["doc_id"] == target.id for row in index.rows.values())
    await keep.refresh_from_db()
    assert keep.status == DocumentStatus.COMPLETED


@pytest.mark.asyncio
@pytest.mark.parametrize("vectors", [[[float("nan"), 0.2]], [[float("inf"), 0.2]], [["not-number"]], [[True, 0.2]]])
async def test_invalid_embedding_is_reported_and_never_saved_as_completed(kb_setup, monkeypatch, vectors):
    client, owner, _, _, index = kb_setup
    async def malformed(texts):
        return vectors
    monkeypatch.setattr(index, "embed", malformed)
    kb = (await save(client, owner)).json()["data"]
    doc = await Document.get(id=kb["documents"][0]["id"])
    assert doc.status == DocumentStatus.FAILED and doc.markdown
    assert not index.rows and not await DocumentChunk.all().exists()


@pytest.mark.asyncio
async def test_partial_vector_write_and_cleanup_failure_are_recoverable(kb_setup, monkeypatch):
    client, owner, _, _, index = kb_setup
    put = index.put
    async def partial(kb_id, rows):
        await put(kb_id, rows[:1])
        raise ConnectionError("partial vector write")
    async def cleanup_offline(ids):
        raise ConnectionError("cleanup offline")
    with monkeypatch.context() as patch:
        patch.setattr(index, "put", partial)
        patch.setattr(index, "remove", cleanup_offline)
        kb = (await save(client, owner)).json()["data"]
    doc = await Document.get(id=kb["documents"][0]["id"])
    assert doc.status == DocumentStatus.FAILED and set(index.rows) <= set(doc.cleanup_vector_ids)
    assert (await client.post(f"/knowledge-bases/{kb['id']}/retry", headers=token(owner))).status_code == 200
    await doc.refresh_from_db()
    assert doc.status == DocumentStatus.COMPLETED and not doc.cleanup_vector_ids
    assert set(index.rows) == set(await DocumentChunk.all().values_list("chroma_id", flat=True))


@pytest.mark.asyncio
@pytest.mark.parametrize("size,success", [(7, True), (8, True), (9, False)])
async def test_skill_single_upload_exact_limit_and_one_byte_over(setup, monkeypatch, size, success):
    client, owner, _, skill = setup
    monkeypatch.setattr(PROJECT_CONFIG, "SKILL_RESOURCE_MAX_BYTES", 8)
    monkeypatch.setattr(PROJECT_CONFIG, "SKILL_RESOURCE_TOTAL_MAX_BYTES", 16)
    result = await submit(client, owner, form(skill, resource_usage="读取附件"), [("files", ("r.md", b"a" * size))])
    assert (result["status"] == "success") is success
    assert len(list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob("**/manifest.json"))) == int(success)


@pytest.mark.asyncio
@pytest.mark.parametrize("second_size,success", [(3, True), (4, True), (5, False)])
async def test_skill_aggregate_exact_limit_and_one_byte_over(setup, monkeypatch, second_size, success):
    client, owner, _, skill = setup
    monkeypatch.setattr(PROJECT_CONFIG, "SKILL_RESOURCE_MAX_BYTES", 8)
    monkeypatch.setattr(PROJECT_CONFIG, "SKILL_RESOURCE_TOTAL_MAX_BYTES", 8)
    result = await submit(client, owner, form(skill, resource_usage="读取两份附件"),
        [("files", ("one.md", b"1234")), ("files", ("two.md", b"a" * second_size))])
    assert (result["status"] == "success") is success
    assert not list(Path(PROJECT_CONFIG.SKILL_BUILD_DIR).glob(".uploads/*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["stale-version", "blank-usage", "missing-classification"])
async def test_invalid_edit_preserves_previous_skill_version_and_download(setup, mode):
    client, owner, _, skill = setup
    first = (await submit(client, owner, form(skill)))["data"]
    data = form(skill, skill_name="不能生效的修改", resource_usage="读取规则")
    files = [("files", ("rules.md", b"new"))]
    if mode == "stale-version":
        data["expected_version"] = "0.0.0"
    elif mode == "blank-usage":
        data["resource_usage"] = " \t "
    else:
        data["resource_categories"] = []
    assert (await submit(client, owner, data, files))["status"] == "failure"
    current = (await client.get(f"/skills/{skill.id}/definition", headers=token(owner))).json()["data"]
    assert current["version"] == first["version"] and current["build"]["build_id"] == first["build_id"]
    assert (await client.get(f"/skills/{skill.id}/builds/{first['build_id']}/download", headers=token(owner))).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["../escape.md", "bad\\path.md", "NUL.md", "bad.md."])
async def test_knowledge_bad_filename_cleans_earlier_staged_file(kb_setup, filename):
    client, owner, _, _, _ = kb_setup
    result = await save(client, owner, files=[("files", ("good.md", b"valid")), ("files", (filename, b"invalid"))])
    assert result.status_code == 400
    assert not list(PROJECT_CONFIG.upload_path.glob("*/*"))


@pytest.mark.asyncio
async def test_stale_generation_editor_does_not_replace_newer_original(kb_setup):
    client, owner, _, _, _ = kb_setup
    kb = (await save(client, owner)).json()["data"]
    doc_id = kb["documents"][0]["id"]
    url = f"/knowledge-bases/{kb['id']}/documents/{doc_id}/content"
    payload = {"content": "new rule", "change_summary": "更新", "expected_generation": 1}
    assert (await client.put(url, headers=token(owner), json=payload)).status_code == 200
    before = (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]
    assert (await client.put(url, headers=token(owner), json={**payload, "content": "stale"})).status_code == 409
    after = (await client.get(f"/knowledge-bases/{kb['id']}", headers=token(owner))).json()["data"]
    assert before == after
    assert len(list(PROJECT_CONFIG.upload_path.glob("*/*"))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining", [[], ["vector-still-present"]])
async def test_chroma_delete_checks_for_residual_vectors(monkeypatch, remaining):
    import sys
    from types import SimpleNamespace
    from applications.knowledge_base.services.document_pipeline import ChromaIndex
    class Collection:
        def delete(self, *, ids):
            assert ids == ["vector-still-present"]
        def get(self, *, ids, include):
            return {"ids": remaining}
    monkeypatch.setitem(sys.modules, "applications.base.rag.chroma_store",
                        SimpleNamespace(chroma_store=SimpleNamespace(_collection=Collection())))
    if remaining:
        with pytest.raises(RuntimeError, match="残留"):
            await ChromaIndex().remove(["vector-still-present"])
    else:
        await ChromaIndex().remove(["vector-still-present"])


@pytest.mark.asyncio
async def test_repeated_delete_callbacks_only_clean_once(kb_setup, monkeypatch):
    client, owner, _, service, index = kb_setup
    kb, keep, target = await two_documents(client, owner)
    _, jobs = await service.save(owner, KnowledgeForm(**{**FORM, "change_summary": "删除",
        "retained_document_ids": [keep.id]}), [], kb_id=kb["id"])
    original, calls = index.remove, []
    async def count(ids):
        calls.append(ids)
        await asyncio.sleep(0)
        return await original(ids)
    monkeypatch.setattr(index, "remove", count)
    await asyncio.gather(*(service.process(jobs[0]) for _ in range(3)))
    assert len(calls) == 1 and not await Document.filter(id=target.id).exists()


@pytest.mark.asyncio
async def test_waiting_for_one_document_does_not_lock_another(kb_setup):
    from applications.knowledge_base.services.document_lock import document_lock
    client, owner, _, service, _ = kb_setup
    kb, keep, target = await two_documents(client, owner)
    _, jobs = await service.save(owner, KnowledgeForm(**{**FORM, "change_summary": "删除",
        "retained_document_ids": [keep.id]}), [], kb_id=kb["id"])
    async with document_lock(keep.id):
        await asyncio.wait_for(service.process(jobs[0]), 2)
    assert not await Document.filter(id=target.id).exists()


@pytest.mark.asyncio
async def test_replacing_processing_file_returns_conflict_and_preserves_original(kb_setup):
    client, owner, _, _, _ = kb_setup
    kb = (await save(client, owner)).json()["data"]
    doc = await Document.get(id=kb["documents"][0]["id"])
    old = Path(doc.file_path).read_bytes()
    await Document.filter(id=doc.id).update(status=DocumentStatus.PROCESSING)
    response = await save(client, owner, {**FORM, "change_summary": "替换处理中文档"},
        files=[("files", ("rules.md", b"replacement"))], kb_id=kb["id"])
    assert response.status_code == 409 and Path(doc.file_path).read_bytes() == old
    assert len(list(PROJECT_CONFIG.upload_path.glob("*/*"))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("vectors", [[], [[0.1]], [[0.1], [0.1, 0.2]]])
async def test_embedding_count_and_dimension_mismatch_keep_parsed_preview(kb_setup, monkeypatch, vectors):
    from applications.knowledge_base.services import document_pipeline
    client, owner, _, _, index = kb_setup
    monkeypatch.setattr(document_pipeline, "chunk_document", lambda *args, **kwargs: [
        {"content": "first"}, {"content": "second"}])
    async def malformed(texts):
        return vectors
    monkeypatch.setattr(index, "embed", malformed)
    kb = (await save(client, owner)).json()["data"]
    doc = await Document.get(id=kb["documents"][0]["id"])
    assert doc.status == DocumentStatus.FAILED and doc.markdown and not index.rows


@pytest.mark.asyncio
async def test_actual_50mib_file_is_allowed_and_one_extra_byte_is_rejected(setup):
    client, owner, _, skill = setup
    limit = 50 * 1024 * 1024
    assert PROJECT_CONFIG.SKILL_RESOURCE_MAX_BYTES == PROJECT_CONFIG.SKILL_RESOURCE_TOTAL_MAX_BYTES == limit
    good = await submit(client, owner, form(skill, resource_usage="读取附件"), [("files", ("rules.md", b"x" * limit))])
    assert good["status"] == "success"
    failed = await submit(client, owner, form(skill, resource_usage="读取附件"), [("files", ("rules.md", b"x" * (limit + 1)))])
    assert failed["status"] == "failure"
    current = (await client.get(f"/skills/{skill.id}/definition", headers=token(owner))).json()["data"]
    assert current["version"] == "1.0.0" and current["build"]["build_id"] == good["data"]["build_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["file", "zip"])
async def test_download_rejects_corrupted_package_through_http(setup, fault):
    client, owner, _, skill = setup
    built = (await submit(client, owner, form(skill)))["data"]
    path = Path(built["skill_directory"]) / "SKILL.md" if fault == "file" else Path(built["workspace_dir"]) / "package.zip"
    path.write_bytes(b"corrupted")
    response = await client.get(f"/skills/{skill.id}/builds/{built['build_id']}/download", headers=token(owner))
    assert "application/zip" not in response.headers.get("content-type", "")
    assert response.json()["status"] == "failure"
