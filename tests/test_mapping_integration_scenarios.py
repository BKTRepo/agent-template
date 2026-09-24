import asyncio
import inspect
import json
from io import BytesIO

import pytest
from openpyxl import Workbook
from tortoise import Tortoise

from applications.jiayueyang.models.feedback_model import RagAnswerFeedback
from applications.jiayueyang.models.mapping_evidence_model import RagTermMappingEvidence
from applications.jiayueyang.models.term_mapping_model import (
    RagTermMappingLearned,
    RagTermMappingSource,
)
from applications.jiayueyang.rag import query as query_module
from applications.jiayueyang.rag.query import QueryParam, hybrid_query, naive_query
from applications.jiayueyang.rag.query_rewriter import BilingualQuery
from applications.jiayueyang.schemas.feedback_schema import FeedbackActionRequest
from applications.jiayueyang.services.mapping_evidence_service import (
    mapping_evidence_service,
    query_fingerprint,
)
from applications.jiayueyang.services.query_memory_sync import query_memory_sync_service
from applications.jiayueyang.services.term_mapping_import_service import (
    TEMPLATE_COLUMNS,
    term_mapping_import_service,
)
from configure import PROJECT_CONFIG


async def _init_db(*models):
    # 这些模型在测试模块导入时都已注册；每个测试统一配置，避免
    # Tortoise 在另一个模型保存时访问到未绑定的默认连接。
    all_models = {
        "applications.jiayueyang.models.conversation_model",
        "applications.jiayueyang.models.feedback_model",
        "applications.jiayueyang.models.mapping_evidence_model",
        "applications.jiayueyang.models.term_mapping_model",
    }
    all_models.update(models)
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": list(all_models)})
    await Tortoise.generate_schemas()


def _xlsx(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(TEMPLATE_COLUMNS))
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


@pytest.mark.asyncio
async def test_revoked_milvus_delete_failure_is_retried(monkeypatch):
    await _init_db("applications.jiayueyang.models.feedback_model")
    try:
        row = await RagAnswerFeedback.create(
            feedback_uid="fb-delete-retry",
            action="revoked",
            index_status="delete_pending",
            original_query="追加授权",
        )
        calls = 0

        def delete_with_one_failure(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Milvus temporarily unavailable")
            return 1

        monkeypatch.setattr(
            "applications.jiayueyang.services.query_memory_sync.delete_query_memory",
            delete_with_one_failure,
        )
        first = await query_memory_sync_service.sync_feedback(row.feedback_uid)
        assert first["status"] == "delete_failed"
        await row.refresh_from_db()
        assert row.index_status == "delete_failed"

        batch = await query_memory_sync_service.sync_pending_feedback()
        assert batch["deleted"] == 1
        await row.refresh_from_db()
        assert row.index_status == "deleted"
        assert calls == 2
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_excel_mapping_import_checks_conflict_and_is_idempotent():
    await _init_db("applications.jiayueyang.models.term_mapping_model")
    try:
        conflict_file = _xlsx([
            ["增量授权", "追加授权", "Incremental Authorization", "IA", "Visa", "row 1"],
            ["预授权", "追加授权", "Preauthorization", "PA", "Visa", "row 2"],
        ])
        preview = await term_mapping_import_service.preview(conflict_file, "conflict.xlsx")
        assert preview["can_import"] is False
        assert preview["conflicts"]

        valid_file = _xlsx([
            ["增量授权", "追加授权", "Incremental Authorization", "IA", "Visa", "row 1"],
        ])
        first = await term_mapping_import_service.import_file(
            valid_file, "mapping.xlsx", upload_batch_id="batch-1", operator="tester",
        )
        assert first["created_count"] == 1
        assert first["updated_count"] == 0

        second = await term_mapping_import_service.import_file(
            valid_file, "mapping.xlsx", upload_batch_id="batch-1", operator="tester",
        )
        assert second["created_count"] == 0
        assert second["updated_count"] == 1
        assert await RagTermMappingSource.all().count() == 1
        row = await RagTermMappingSource.get(mapping_key="增量授权|visa")
        assert row.version == 2
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_feedback_endpoint_dispatches_to_sync_and_mapping_tasks(monkeypatch):
    from applications.jiayueyang.models.conversation_model import (
        MSG_DONE,
        RagConversation,
        RagConversationMessage,
        RagConversationRetrieval,
    )
    from applications.jiayueyang.services.feedback_service import feedback_service
    from applications.jiayueyang.views.chat_view import set_answer_feedback

    await _init_db(
        "applications.jiayueyang.models.conversation_model",
        "applications.jiayueyang.models.feedback_model",
        "applications.jiayueyang.models.mapping_evidence_model",
        "applications.jiayueyang.models.term_mapping_model",
    )
    try:
        conversation = await RagConversation.create(title="测试采纳")
        await RagConversationMessage.create(
            conversation=conversation, seq=0, role="user", content="追家授权怎么处理",
            status=MSG_DONE,
        )
        await RagConversationMessage.create(
            conversation=conversation, seq=1, role="assistant", content="答案一",
            status=MSG_DONE,
        )
        await RagConversationMessage.create(
            conversation=conversation, seq=2, role="user", content="追家授权需要哪些字段",
            status=MSG_DONE,
        )
        await RagConversationMessage.create(
            conversation=conversation, seq=3, role="assistant", content="答案二",
            status=MSG_DONE,
        )
        detail = {
            "metadata": {
                "resolved_query": "追家授权怎么处理",
                "rewritten_query": "增量授权 Incremental Authorization 怎么处理",
                "english_query": "Incremental Authorization",
                "scope_doc_ids": ["doc-card"],
            },
            "chunks": [{"id": "chunk-1", "doc_id": "doc-card", "content": "增量授权说明"}],
        }
        await RagConversationRetrieval.create(conversation=conversation, message_seq=1, detail=detail)
        detail["metadata"]["resolved_query"] = "追家授权需要哪些字段"
        await RagConversationRetrieval.create(conversation=conversation, message_seq=3, detail=detail)

        async def fake_chat(*args, **kwargs):
            return json.dumps({"mappings": [{
                "aliases_zh": ["追家授权"],
                "canonical_zh": "增量授权",
                "official_en": "Incremental Authorization",
                "aliases_en": [],
                "scope": "银行卡授权业务",
                "confidence": 0.9,
            }]}, ensure_ascii=False)

        async def same_vectors(texts, quick=True):
            return [[1.0, 0.0] for _ in texts]

        monkeypatch.setattr(
            "applications.jiayueyang.services.mapping_evidence_service.chat_completion",
            fake_chat,
        )
        monkeypatch.setattr(
            "applications.jiayueyang.services.mapping_evidence_service.embed_texts",
            same_vectors,
        )
        monkeypatch.setattr(
            "applications.jiayueyang.services.query_memory_sync.embed_texts",
            same_vectors,
        )
        monkeypatch.setattr(
            "applications.jiayueyang.services.query_memory_sync.upsert_query_memory",
            lambda records: len(records),
        )

        dispatch_count = 0

        async def run_task(task, args, label):
            nonlocal dispatch_count
            result = task.run(*args)
            if inspect.isawaitable(result):
                await result
            dispatch_count += 1

        monkeypatch.setattr(feedback_service, "_dispatch_after_response", run_task)
        await set_answer_feedback(
            conversation.id, 1, FeedbackActionRequest(action="accepted"),
        )
        await set_answer_feedback(
            conversation.id, 3, FeedbackActionRequest(action="accepted"),
        )
        for _ in range(100):
            if dispatch_count >= 4:
                break
            await asyncio.sleep(0.01)
        assert dispatch_count == 4

        feedback_rows = await RagAnswerFeedback.filter(action="accepted").all()
        assert len(feedback_rows) == 2
        assert all(row.index_status == "synced" for row in feedback_rows)
        assert all(
            row.mapping_extract_status == "succeeded" for row in feedback_rows
        ), [(row.feedback_uid, row.mapping_extract_status, row.mapping_extract_error) for row in feedback_rows]
        learned = await RagTermMappingLearned.get(mapping_key="增量授权")
        assert learned.status == "active"
        assert learned.evidence_count == 2
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_guidance_switches_and_scoped_fallback(monkeypatch):
    calls = []

    async def fake_guidance(query):
        calls.append(query)
        return {
            "matched": True,
            "matched_feedback_ids": ["fb-guided"],
            "feedback_scores": {"fb-guided": 0.91},
            "scope_doc_ids": ["doc-guided"],
            "fallback_reason": None,
        }

    monkeypatch.setattr(query_module, "recall_query_guidance", fake_guidance)
    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_ENABLED", True)

    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_SCOPED_SEARCH_ENABLED", False)
    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_SHADOW_MODE", False)
    guidance, filter_expr, shadow = await query_module._prepare_query_guidance("问题一")
    assert filter_expr == ""
    assert shadow is False
    assert guidance["scope_doc_ids"] == []
    assert calls == []

    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_SCOPED_SEARCH_ENABLED", True)
    guidance, filter_expr, shadow = await query_module._prepare_query_guidance("问题二")
    assert '"doc-guided"' in filter_expr
    assert shadow is False

    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_SCOPED_SEARCH_ENABLED", False)
    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_SHADOW_MODE", True)
    guidance, filter_expr, shadow = await query_module._prepare_query_guidance("问题三")
    assert filter_expr == ""
    assert shadow is True
    assert calls == ["问题二", "问题三"]

    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_SCOPED_SEARCH_ENABLED", True)
    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_SHADOW_MODE", False)
    monkeypatch.setattr(query_module, "resolve_query_with_history", lambda q, h: q)

    async def fake_resolve(q, h):
        return q

    async def fake_mapping(q):
        return {"status": "unmatched", "matches": [], "conflicts": []}

    async def fake_rewrite(q, **kwargs):
        return BilingualQuery(q, q, "")

    async def fake_decompose(q):
        return []

    monkeypatch.setattr(query_module, "resolve_query_with_history", fake_resolve)
    monkeypatch.setattr(query_module.term_mapping_service, "resolve", fake_mapping)
    monkeypatch.setattr(query_module, "rewrite_query_bilingual", fake_rewrite)
    monkeypatch.setattr(query_module, "decompose_query", fake_decompose)
    retrieve_calls = []

    async def fake_retrieve(*args, **kwargs):
        filter_expr = kwargs.get("filter_expr", "")
        retrieve_calls.append(filter_expr)
        if filter_expr:
            return []
        return [[{
            "id": "chunk-fallback", "doc_id": "doc-all", "content": "全库证据", "score": 0.8,
        }]]

    monkeypatch.setattr(query_module, "_retrieve_ranked_lists", fake_retrieve)
    monkeypatch.setattr(PROJECT_CONFIG, "DOC_RECALL_ENABLED", False)
    result = await naive_query("问题四", QueryParam(only_need_context=True, enable_rerank=False))
    assert set(retrieve_calls) == {'doc_id in ["doc-guided"]', ""}
    assert result.raw_data["metadata"]["fallback_reason"] == "no_scoped_chunks"
    assert result.raw_data["metadata"]["guidance_fallback"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["naive", "hybrid"])
async def test_guided_and_global_candidates_share_one_rerank(monkeypatch, mode):
    async def fake_guidance(_query):
        return {"matched": True, "matched_feedback_ids": ["fb-1"],
                "feedback_scores": {"fb-1": 0.9}, "scope_doc_ids": ["old-doc"],
                "fallback_reason": None}

    async def fake_resolve(query, _history):
        return query

    async def fake_mapping(_query):
        return {"status": "unmatched", "matches": [], "conflicts": []}

    async def fake_rewrite(query, **_kwargs):
        return BilingualQuery(query, query, "")

    async def fake_decompose(_query):
        return []

    async def fake_candidates(*_args, **kwargs):
        if kwargs.get("filter_expr"):
            chunks = [{"id": "old", "doc_id": "old-doc", "content": "旧文档证据"}]
        else:
            chunks = [{"id": "new", "doc_id": "new-doc", "content": "新增问题的全库证据"}]
        return [chunks] if mode == "naive" else chunks

    rerank_calls = []

    async def fake_rerank(*, query, chunks, top_n):
        rerank_calls.append([item["id"] for item in chunks])
        return [dict(item, rerank_score=0.9) for item in chunks]

    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_ENABLED", True)
    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_SCOPED_SEARCH_ENABLED", True)
    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_SHADOW_MODE", False)
    monkeypatch.setattr(PROJECT_CONFIG, "DOC_RECALL_ENABLED", False)
    monkeypatch.setattr(query_module, "recall_query_guidance", fake_guidance)
    monkeypatch.setattr(query_module, "resolve_query_with_history", fake_resolve)
    monkeypatch.setattr(query_module.term_mapping_service, "resolve", fake_mapping)
    monkeypatch.setattr(query_module, "rewrite_query_bilingual", fake_rewrite)
    monkeypatch.setattr(query_module, "decompose_query", fake_decompose)
    monkeypatch.setattr(query_module, "rerank_chunks", fake_rerank)
    target = "_retrieve_ranked_lists" if mode == "naive" else "_get_hybrid_context"
    monkeypatch.setattr(query_module, target, fake_candidates)

    run_query = naive_query if mode == "naive" else hybrid_query
    result = await run_query("追加授权及新增问题", QueryParam(
        only_need_context=True, enable_rerank=True, chunk_top_k=10, rrf_top_k=10,
    ))
    assert len(rerank_calls) == 1
    assert set(rerank_calls[0]) == {"old", "new"}
    assert result.raw_data["metadata"]["guided_candidate_count"] == 1
    assert result.raw_data["metadata"]["global_candidate_count"] == 1
    assert ":guided+global" in result.raw_data["metadata"]["retrieval_route"]


def test_guided_weight_keeps_global_documents_in_candidate_pool(monkeypatch):
    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_GUIDED_WEIGHT", 1.2)
    monkeypatch.setattr(PROJECT_CONFIG, "QUERY_MEMORY_GLOBAL_MIN_RATIO", 0.30)
    guided = [
        {"id": f"old-{i}", "doc_id": "old-doc", "content": f"旧证据 {i}"}
        for i in range(8)
    ]
    global_chunks = [
        {"id": f"new-{i}", "doc_id": "new-doc", "content": f"新证据 {i}"}
        for i in range(8)
    ]
    result = query_module._blend_guided_candidates(
        global_chunks, guided, ["old-doc"], top_k=10,
    )
    assert len(result) == 10
    assert len([item for item in result if item["doc_id"] == "new-doc"]) >= 3
    assert len([item for item in result if item["doc_id"] == "old-doc"]) >= 1
