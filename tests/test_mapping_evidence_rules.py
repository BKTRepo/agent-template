import asyncio
import json
from types import SimpleNamespace

import pytest

from applications.jiayueyang.services.mapping_evidence_service import (
    _extract_proposals,
    _independent_component,
    mapping_key_for,
    normalize_query_for_fingerprint,
    query_fingerprint,
)
from applications.jiayueyang.models.feedback_model import RagAnswerFeedback
from applications.jiayueyang.models.mapping_evidence_model import RagTermMappingEvidence
from applications.jiayueyang.models.term_mapping_model import (
    RagTermMappingLearned,
    RagTermMappingSource,
)
from applications.jiayueyang.services.mapping_evidence_service import mapping_evidence_service
from applications.jiayueyang.services.term_mapping_service import term_mapping_service
from tortoise import Tortoise
from configure import PROJECT_CONFIG


def _feedback(**overrides):
    data = {
        "original_query": "追家授权怎么处理",
        "resolved_query": "追家授权怎么处理",
        "rewritten_query": "增量授权 Incremental Authorization 怎么处理",
        "english_query": "Incremental Authorization",
        "scope": "银行卡授权业务",
        "retrieval_snapshot": {
            "chunks": [{"doc_id": "doc-1", "content": "增量授权是原授权基础上的追加授权金额。"}],
        },
        "related_doc_ids": ["doc-1"],
        "related_chunk_ids": ["chunk-1"],
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_query_fingerprint_ignores_punctuation_and_spacing():
    assert normalize_query_for_fingerprint("  VISA 39？  ") == "visa 39"
    assert query_fingerprint("VISA-39") == query_fingerprint("visa 39")


def test_mapping_key_ignores_optional_scope():
    assert mapping_key_for("增量授权", "银行卡授权业务") == "增量授权"
    assert mapping_key_for("增量授权", None) == "增量授权"


@pytest.mark.asyncio
async def test_extraction_requires_alias_in_original_and_canonical_in_evidence(monkeypatch):
    async def fake_chat_completion(*args, **kwargs):
        return json.dumps({
            "mappings": [{
                "aliases_zh": ["追家授权"],
                "canonical_zh": "增量授权",
                "official_en": "Incremental Authorization",
                "aliases_en": [],
                "scope": "银行卡授权业务",
                "confidence": 0.9,
            }]
        }, ensure_ascii=False)

    monkeypatch.setattr(
        "applications.jiayueyang.services.mapping_evidence_service.chat_completion",
        fake_chat_completion,
    )
    proposals = await _extract_proposals(_feedback())
    assert len(proposals) == 1
    assert proposals[0]["aliases_zh"] == ["追家授权"]
    assert proposals[0]["mapping_key"] == "增量授权"


@pytest.mark.asyncio
async def test_extraction_discards_unverifiable_alias(monkeypatch):
    async def fake_chat_completion(*args, **kwargs):
        return json.dumps({
            "mappings": [{
                "aliases_zh": ["模型猜测词"],
                "canonical_zh": "增量授权",
                "official_en": "Incremental Authorization",
                "confidence": 0.99,
            }]
        }, ensure_ascii=False)

    monkeypatch.setattr(
        "applications.jiayueyang.services.mapping_evidence_service.chat_completion",
        fake_chat_completion,
    )
    assert await _extract_proposals(_feedback()) == []


@pytest.mark.asyncio
async def test_evidence_group_does_not_use_similarity_bridges_or_low_confidence(monkeypatch):
    rows = [
        SimpleNamespace(query_fingerprint=f"fingerprint-{index}", created_time=None,
                        query_text=f"question-{index}", official_en="Incremental Authorization",
                        extraction_confidence=confidence)
        for index, confidence in enumerate((0.9, 0.9, 0.9, 0.7))
    ]
    # A-B 和 B-C 相近，A-C 不相近。D 置信度不足，虽然向量相同也不能计数。
    vectors = [[1.0, 0.0], [0.819, 0.574], [0.342, 0.940]]

    async def fake_embed(texts, quick=True):
        assert texts == ["question-0", "question-1", "question-2"]
        return vectors

    monkeypatch.setattr(PROJECT_CONFIG, "MAPPING_EVIDENCE_MIN_SCORE", 0.72)
    monkeypatch.setattr(PROJECT_CONFIG, "MAPPING_EVIDENCE_MIN_CONFIDENCE", 0.80)
    monkeypatch.setattr(PROJECT_CONFIG, "MAPPING_EVIDENCE_CENTROID_MIN_SCORE", 0.90)
    monkeypatch.setattr(
        "applications.jiayueyang.services.mapping_evidence_service.embed_texts", fake_embed,
    )
    group = await _independent_component(rows)
    assert len(group) == 2
    assert set(row.query_text for row in group) == {"question-0", "question-1"}


@pytest.mark.asyncio
async def test_centroid_limit_rejects_overly_broad_evidence_group(monkeypatch):
    rows = [
        SimpleNamespace(query_fingerprint=f"fingerprint-{index}", created_time=None,
                        query_text=f"question-{index}", official_en=None,
                        extraction_confidence=0.9)
        for index in range(4)
    ]
    # 任意两条相似度都是 0.725；四条合并时每条与组中心仅约 0.891。
    vectors = [[0.725 ** 0.5] + [0.275 ** 0.5 if position == index else 0.0
                                  for position in range(4)] for index in range(4)]

    async def fake_embed(texts, quick=True):
        return vectors

    monkeypatch.setattr(PROJECT_CONFIG, "MAPPING_EVIDENCE_MIN_SCORE", 0.72)
    monkeypatch.setattr(PROJECT_CONFIG, "MAPPING_EVIDENCE_MIN_CONFIDENCE", 0.80)
    monkeypatch.setattr(PROJECT_CONFIG, "MAPPING_EVIDENCE_CENTROID_MIN_SCORE", 0.90)
    monkeypatch.setattr(
        "applications.jiayueyang.services.mapping_evidence_service.embed_texts", fake_embed,
    )
    assert len(await _independent_component(rows)) == 3


@pytest.mark.asyncio
async def test_first_evidence_waits_for_second_independent_feedback(monkeypatch):
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": [
            "applications.jiayueyang.models.feedback_model",
            "applications.jiayueyang.models.mapping_evidence_model",
            "applications.jiayueyang.models.term_mapping_model",
        ]},
    )
    await Tortoise.generate_schemas()
    try:
        async def valid_source(_proposal):
            return "valid"

        async def same_vectors(texts, quick=True):
            return [[1.0, 0.0] for _ in texts]

        monkeypatch.setattr(mapping_evidence_service, "_source_conflict", valid_source)
        monkeypatch.setattr(
            "applications.jiayueyang.services.mapping_evidence_service.embed_texts",
            same_vectors,
        )
        proposal = {
            "canonical_zh": "增量授权",
            "aliases_zh": ["追家授权"],
            "official_en": "Incremental Authorization",
            "aliases_en": [],
            "scope": "银行卡授权业务",
            "normalized_keys": ["增量授权", "追家授权", "incremental authorization"],
            "mapping_key": "增量授权",
            "supporting_doc_ids": ["doc-1"],
            "supporting_chunk_ids": ["chunk-1"],
            "extraction_confidence": 0.9,
            "extraction_payload": {},
        }

        first = await RagAnswerFeedback.create(
            feedback_uid="fb-first",
            action="accepted",
            index_status="synced",
            original_query="追家授权怎么处理",
            resolved_query="追家授权怎么处理",
            query_fingerprint=query_fingerprint("追家授权怎么处理"),
        )
        await mapping_evidence_service._save_evidence(first, proposal)
        assert await mapping_evidence_service._aggregate(proposal["mapping_key"]) is None

        second = await RagAnswerFeedback.create(
            feedback_uid="fb-second",
            action="accepted",
            index_status="synced",
            original_query="追家授权需要哪些字段",
            resolved_query="追家授权需要哪些字段",
            query_fingerprint=query_fingerprint("追家授权需要哪些字段"),
        )
        await mapping_evidence_service._save_evidence(second, proposal)
        learned = await mapping_evidence_service._aggregate(proposal["mapping_key"])
        assert learned is not None
        assert learned.status == "active"
        assert learned.evidence_count == 2
        assert set(learned.source_feedback_ids) == {"fb-first", "fb-second"}
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_concurrent_aggregate_recovers_from_mapping_key_conflict(monkeypatch):
    """即时任务与 Beat 同时聚合时，唯一键冲突应重查而不是失败。"""
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": [
            "applications.jiayueyang.models.feedback_model",
            "applications.jiayueyang.models.mapping_evidence_model",
            "applications.jiayueyang.models.term_mapping_model",
        ]},
    )
    await Tortoise.generate_schemas()
    try:
        async def valid_source(_proposal):
            return "valid"

        async def same_vectors(texts, quick=True):
            return [[1.0, 0.0] for _ in texts]

        monkeypatch.setattr(mapping_evidence_service, "_source_conflict", valid_source)
        monkeypatch.setattr(
            "applications.jiayueyang.services.mapping_evidence_service.embed_texts",
            same_vectors,
        )
        proposal = {
            "canonical_zh": "增量授权",
            "aliases_zh": ["追家授权"],
            "official_en": "Incremental Authorization",
            "aliases_en": [],
            "scope": "银行卡授权业务",
            "normalized_keys": ["增量授权", "追家授权", "incremental authorization"],
            "mapping_key": "增量授权",
            "supporting_doc_ids": ["doc-1"],
            "supporting_chunk_ids": ["chunk-1"],
            "extraction_confidence": 0.9,
            "extraction_payload": {},
        }
        for feedback_uid, query in (
            ("fb-race-1", "追家授权怎么处理"),
            ("fb-race-2", "追家授权需要哪些字段"),
        ):
            feedback = await RagAnswerFeedback.create(
                feedback_uid=feedback_uid,
                action="accepted",
                index_status="synced",
                original_query=query,
                resolved_query=query,
                query_fingerprint=query_fingerprint(query),
            )
            await mapping_evidence_service._save_evidence(feedback, proposal)

        original_create = RagTermMappingLearned.create
        create_calls = 0

        async def create_then_report_conflict(**kwargs):
            nonlocal create_calls
            create_calls += 1
            row = await original_create(**kwargs)
            if create_calls == 1:
                # 模拟另一个 Worker 已经提交了插入，但本任务收到唯一键异常。
                from tortoise.exceptions import IntegrityError
                raise IntegrityError("duplicate mapping_key")
            return row

        monkeypatch.setattr(RagTermMappingLearned, "create", create_then_report_conflict)
        results = await asyncio.gather(
            mapping_evidence_service._aggregate("增量授权"),
            mapping_evidence_service._aggregate("增量授权"),
        )

        rows = await RagTermMappingLearned.filter(mapping_key="增量授权").all()
        assert len(rows) == 1
        assert all(result is not None for result in results)
        assert rows[0].status == "active"
        assert rows[0].evidence_count == 2
        assert set(rows[0].source_feedback_ids) == {"fb-race-1", "fb-race-2"}
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_evidence_with_different_scopes_can_share_learned_mapping(monkeypatch):
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": [
            "applications.jiayueyang.models.feedback_model",
            "applications.jiayueyang.models.mapping_evidence_model",
            "applications.jiayueyang.models.term_mapping_model",
        ]},
    )
    await Tortoise.generate_schemas()
    try:
        async def valid_source(_proposal):
            return "valid"

        async def same_vectors(texts, quick=True):
            return [[1.0, 0.0] for _ in texts]

        monkeypatch.setattr(mapping_evidence_service, "_source_conflict", valid_source)
        monkeypatch.setattr(
            "applications.jiayueyang.services.mapping_evidence_service.embed_texts",
            same_vectors,
        )
        base = {
            "canonical_zh": "增量授权",
            "aliases_zh": ["追家授权"],
            "official_en": "Incremental Authorization",
            "aliases_en": [],
            "normalized_keys": ["增量授权", "追家授权", "incremental authorization"],
            "mapping_key": "增量授权",
            "supporting_doc_ids": ["doc-1"],
            "supporting_chunk_ids": ["chunk-1"],
            "extraction_confidence": 0.9,
            "extraction_payload": {},
        }
        for index, (scope, query) in enumerate([
            ("Visa", "追家授权怎么处理"),
            (None, "追家授权需要哪些字段"),
        ]):
            feedback = await RagAnswerFeedback.create(
                feedback_uid=f"fb-scope-{index}",
                action="accepted",
                index_status="synced",
                original_query=query,
                resolved_query=query,
                query_fingerprint=query_fingerprint(query),
            )
            proposal = {**base, "scope": scope}
            await mapping_evidence_service._save_evidence(feedback, proposal)
        learned = await mapping_evidence_service._aggregate("增量授权")
        assert learned is not None
        assert learned.status == "active"
        assert learned.evidence_count == 2
        assert learned.scope == "Visa"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_query_scope_mismatch_does_not_discard_mapping():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": [
            "applications.jiayueyang.models.feedback_model",
            "applications.jiayueyang.models.mapping_evidence_model",
            "applications.jiayueyang.models.term_mapping_model",
        ]},
    )
    await Tortoise.generate_schemas()
    try:
        await RagTermMappingSource.create(
            mapping_id="source-scope-test",
            mapping_key="增量授权|Visa",
            canonical_zh="增量授权",
            aliases_zh=["追家授权"],
            official_en="Incremental Authorization",
            aliases_en=[],
            scope="Visa",
            normalized_keys=["增量授权", "追家授权", "incremental authorization"],
            status="enabled",
            upload_batch_id="test",
        )
        result = await term_mapping_service.resolve("追家授权怎么处理", scope="Mastercard")
        assert result["status"] == "determined"
        assert result["matches"][0]["canonical_zh"] == "增量授权"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_source_mappings_cover_all_terms_and_learned_fills_only_gaps():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["applications.jiayueyang.models.term_mapping_model"]},
    )
    await Tortoise.generate_schemas()
    try:
        for mapping_id, canonical, alias, english in (
            ("source-auth", "增量授权", "追加授权", "Incremental Authorization"),
            ("source-refund", "冲正", "撤销交易", "Reversal"),
        ):
            await RagTermMappingSource.create(
                mapping_id=mapping_id, mapping_key=f"{canonical}|信用卡",
                canonical_zh=canonical, aliases_zh=[alias], official_en=english,
                status="enabled", upload_batch_id="test",
            )
        await RagTermMappingLearned.create(
            learned_mapping_id="learned-auth-shadowed", mapping_key="其他授权",
            canonical_zh="其他授权", aliases_zh=["追加授权"], status="active",
        )
        await RagTermMappingLearned.create(
            learned_mapping_id="learned-field", mapping_key="上送字段",
            canonical_zh="上送字段", aliases_zh=["报文字段"], status="active",
        )

        result = await term_mapping_service.resolve("追加授权的撤销交易和报文字段")
        assert result["status"] == "determined"
        assert [item["canonical_zh"] for item in result["matches"]] == [
            "增量授权", "冲正", "上送字段",
        ]
        assert [item["mapping_source"] for item in result["matches"]] == [
            "source_mapping", "source_mapping", "learned_mapping",
        ]
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_source_mapping_status_is_checked_per_alias(monkeypatch):
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": [
            "applications.jiayueyang.models.feedback_model",
            "applications.jiayueyang.models.mapping_evidence_model",
            "applications.jiayueyang.models.term_mapping_model",
        ]},
    )
    await Tortoise.generate_schemas()
    try:
        await RagTermMappingSource.create(
            mapping_id="source-alias-status",
            mapping_key="增量授权|Visa",
            canonical_zh="增量授权",
            aliases_zh=["追加授权"],
            official_en="Incremental Authorization",
            aliases_en=[],
            scope="Visa",
            normalized_keys=["增量授权", "追加授权", "incremental authorization"],
            status="enabled",
            upload_batch_id="test",
        )
        assert await mapping_evidence_service._source_conflict({
            "canonical_zh": "增量授权",
            "aliases_zh": ["追家授权"],
        }) == "valid"
        assert await mapping_evidence_service._source_conflict({
            "canonical_zh": "增量授权",
            "aliases_zh": ["追加授权"],
        }) == "covered"

        await RagTermMappingSource.create(
            mapping_id="source-alias-conflict",
            mapping_key="预授权|Visa",
            canonical_zh="预授权",
            aliases_zh=["追家授权"],
            official_en="Preauthorization",
            aliases_en=[],
            scope="Visa",
            normalized_keys=["预授权", "追家授权", "preauthorization"],
            status="enabled",
            upload_batch_id="test",
        )
        assert await mapping_evidence_service._source_conflict({
            "canonical_zh": "增量授权",
            "aliases_zh": ["追家授权"],
        }) == "conflict"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_zero_valid_evidence_disables_existing_mapping():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": [
            "applications.jiayueyang.models.feedback_model",
            "applications.jiayueyang.models.mapping_evidence_model",
            "applications.jiayueyang.models.term_mapping_model",
        ]},
    )
    await Tortoise.generate_schemas()
    try:
        learned = await RagTermMappingLearned.create(
            learned_mapping_id="learned-zero-evidence",
            mapping_key="增量授权",
            canonical_zh="增量授权",
            aliases_zh=["追家授权", "追加授权"],
            official_en="Incremental Authorization",
            evidence_count=2,
            status="active",
            source_feedback_ids=["fb-one", "fb-two"],
        )

        result = await mapping_evidence_service._aggregate("增量授权")

        assert result is not None
        await learned.refresh_from_db()
        assert learned.status == "disabled"
        assert learned.evidence_count == 0
        assert learned.source_feedback_ids == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_conflicting_nonempty_official_terms_disable_mapping(monkeypatch):
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": [
            "applications.jiayueyang.models.feedback_model",
            "applications.jiayueyang.models.mapping_evidence_model",
            "applications.jiayueyang.models.term_mapping_model",
        ]},
    )
    await Tortoise.generate_schemas()
    try:
        async def valid_source(_proposal):
            return "valid"

        async def same_vectors(texts, quick=True):
            return [[1.0, 0.0] for _ in texts]

        monkeypatch.setattr(mapping_evidence_service, "_source_conflict", valid_source)
        monkeypatch.setattr(
            "applications.jiayueyang.services.mapping_evidence_service.embed_texts",
            same_vectors,
        )

        base = {
            "canonical_zh": "增量授权",
            "aliases_en": [],
            "scope": None,
            "mapping_key": "增量授权",
            "supporting_doc_ids": ["doc-1"],
            "supporting_chunk_ids": ["chunk-1"],
            "extraction_confidence": 0.9,
            "extraction_payload": {},
        }
        cases = [
            ("fb-en-1", "追家授权怎么处理", "追家授权", "Incremental Authorization"),
            ("fb-en-2", "追加授权怎么处理", "追加授权", None),
            ("fb-en-3", "追增授权怎么处理", "追增授权", "Preauthorization"),
        ]
        for feedback_uid, query, alias, official_en in cases:
            feedback = await RagAnswerFeedback.create(
                feedback_uid=feedback_uid,
                action="accepted",
                index_status="synced",
                original_query=query,
                resolved_query=query,
                query_fingerprint=query_fingerprint(query),
            )
            proposal = {
                **base,
                "aliases_zh": [alias],
                "official_en": official_en,
                "normalized_keys": ["增量授权", alias, official_en or ""],
            }
            await mapping_evidence_service._save_evidence(feedback, proposal)

        # 前两条只有一个非空英文词，可以正常形成 active 映射。
        await RagTermMappingEvidence.filter(feedback_uid="fb-en-3").update(status="revoked")
        learned = await mapping_evidence_service._aggregate("增量授权")
        assert learned is not None
        assert learned.status == "active"

        # 第三条恢复后出现两个不同的非空官方英文词，已有映射必须停用。
        await RagTermMappingEvidence.filter(feedback_uid="fb-en-3").update(status="valid")
        learned = await mapping_evidence_service._aggregate("增量授权")
        assert learned is not None
        assert learned.status == "disabled"
        assert learned.evidence_count == 3
        assert set(learned.source_feedback_ids) == {"fb-en-1", "fb-en-2", "fb-en-3"}
    finally:
        await Tortoise.close_connections()
