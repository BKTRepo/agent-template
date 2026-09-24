import asyncio
import json

from applications.jiayueyang.rag import query as query_module
from applications.jiayueyang.rag.query import (
    TechnicalConstraint,
    _augment_technical_candidates,
    _extract_technical_constraints,
    _prioritize_technical_evidence,
)
from applications.jiayueyang.rag.table_rows import (
    build_code_table_chunks_from_docling_json,
)


def _text(value, page, left, top, label="text"):
    return {
        "label": label,
        "text": value,
        "prov": [{"page_no": page, "bbox": {"l": left, "t": top}}],
    }


def test_docling_code_table_rows_are_recovered(tmp_path):
    path = tmp_path / "sample.json"
    path.write_text(json.dumps({"texts": [
        _text("Table 66 - Response Codes", 7, 20, 100, "caption"),
        _text("Field 39 Response Code", 7, 20, 110),
        _text("Code", 7, 30, 120),
        _text("Description", 7, 100, 120),
        _text("00", 7, 30, 140),
        _text("Approved", 7, 100, 140),
        _text("11", 7, 30, 160),
        _text("Approved (V.I.P.)", 7, 100, 160),
    ]}, ensure_ascii=False), encoding="utf-8")

    rows = build_code_table_chunks_from_docling_json(path, "sample.pdf")

    vip = next(row for row in rows if row["code_value"] == "11")
    assert vip["field_no"] == "39"
    assert "Approved (V.I.P.)" in vip["content"]
    assert vip["table_name"].startswith("Table 66")
    assert vip["source_filename"] == "sample.pdf"


def test_technical_constraints_extract_field_and_processing_code():
    assert _extract_technical_constraints("VISA 39域返回11是什么意思") == [
        TechnicalConstraint("39", "11", "response")
    ]
    assert _extract_technical_constraints("余额查询处理码30") == [
        TechnicalConstraint("3", "", "processing")
    ]
    assert _extract_technical_constraints(
        "What does Field 39 response code 11 mean?"
    ) == [TechnicalConstraint("39", "11", "response")]


def test_exact_technical_evidence_is_prioritized():
    constraint = TechnicalConstraint("39", "11", "response")
    unrelated = {"id": "unrelated", "content": "Field 11 is a trace number."}
    exact = {
        "id": "exact",
        "content": "[代码表行] Table 66 Field 39 Response Codes\n代码: 11 | 内容: Approved (V.I.P.)",
    }
    ranked = _prioritize_technical_evidence([unrelated, exact], [constraint])
    assert [item["id"] for item in ranked] == ["exact", "unrelated"]


def test_neighbor_window_combines_table_header_and_code_row(monkeypatch):
    constraint = TechnicalConstraint("39", "11", "response")
    anchor = {
        "id": "doc-chunk-10",
        "chunk_id": "doc-chunk-10",
        "doc_id": "doc",
        "order": 10,
        "content": "Table 66 Field 39 Response Codes",
        "tokens": 10,
    }
    neighbor = {
        "id": "doc-chunk-11",
        "chunk_id": "doc-chunk-11",
        "doc_id": "doc",
        "order": 11,
        "content": "Code 11 Approved (V.I.P.)",
        "tokens": 8,
    }

    monkeypatch.setattr(query_module, "query_neighbor_chunks", lambda *args: [anchor, neighbor])
    result = asyncio.run(_augment_technical_candidates([anchor], [constraint]))

    context = next(item for item in result if item.get("modality") == "context_window")
    assert "Field 39" in context["content"]
    assert "Approved (V.I.P.)" in context["content"]
    assert context["_technical_evidence_score"] > 0
