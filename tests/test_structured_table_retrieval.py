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
    merge_derived_table_chunks,
)


def _text(value, page, left, top, label="text", right=None):
    bbox = {"l": left, "t": top}
    if right is not None:
        bbox["r"] = right
    return {
        "label": label,
        "text": value,
        "prov": [{"page_no": page, "bbox": bbox}],
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


def test_docling_columns_preserve_blank_cells_and_split_merged_header(tmp_path):
    # 模拟真实 Docling 输出：Client/Visa 粘连，Use 换行，12 的中间列为空。
    path = tmp_path / "columns.json"
    texts = [
        _text("Field 39 - Valid Values", 5, 75, 740, "section_header"),
        _text("Table 66: Response Codes", 5, 75, 720, "caption"),
        _text("Response", 5, 75, 694, right=120),
        _text("Code", 5, 75, 682, right=98),
        _text("Definition", 5, 142, 694, right=188),
        _text("Client Visa", 5, 287, 694, right=340),
        _text("Use", 5, 322, 682, right=338),
        _text("File", 5, 360, 694, right=376),
        _text("Update/", 5, 360, 682, right=398),
        _text("Inquiry", 5, 360, 670, right=394),
        _text("Category", 5, 412, 694, right=454),
        _text("Reattempt", 5, 479, 694, right=530),
        _text("Allowed", 5, 479, 682, right=516),
        _text("11", 5, 75, 650, right=85),
        _text("Approved (V.I.P.)", 5, 142, 650, right=230),
        _text("Yes", 5, 321, 650, right=335),
        _text("Approval", 5, 412, 650, right=449),
        _text("12", 5, 75, 620, right=85),
        _text("Invalid", 5, 142, 620, right=170),
        _text("transaction", 5, 143, 608, right=191),
        _text("Yes", 5, 287, 620, right=301),
        _text("Yes", 5, 321, 620, right=335),
        _text("1", 5, 412, 620, right=415),
        _text("No", 5, 479, 620, right=491),
    ]
    path.write_text(json.dumps({"texts": texts}), encoding="utf-8")
    rows = build_code_table_chunks_from_docling_json(path)
    by_code = {row["code_value"]: row for row in rows}
    columns = {item["column"]: item["value"] for item in by_code["12"]["column_values"]}
    assert columns == {
        "Response Code": "12", "Definition": "Invalid transaction",
        "Client": "Yes", "Visa Use": "Yes", "File Update/Inquiry": "",
        "Category": "1", "Reattempt Allowed": "No",
    }
    assert "Category: 1 | Reattempt Allowed: No" in by_code["12"]["content"]
    assert "File Update/Inquiry: 原表空白（未给值）" in by_code["12"]["content"]
    vip = {item["column"]: item["value"] for item in by_code["11"]["column_values"]}
    assert vip["Client"] == vip["Reattempt Allowed"] == ""
    assert vip["Visa Use"] == "Yes"
    assert all(row["column_alignment"] == "recovered" for row in rows)


def test_docling_column_recovery_is_generic_with_missing_header_node(tmp_path):
    path = tmp_path / "generic.json"
    path.write_text(json.dumps({"texts": [
        _text("Table 2 - Result Codes", 1, 20, 10, "caption"),
        _text("Code", 1, 20, 20, right=45),
        # 两个表头合并，第二列头没有其他节点，但两行正文提供其位置。
        _text("Source Status", 1, 100, 20, right=180),
        _text("01", 1, 20, 40, right=30),
        _text("Local", 1, 100, 40, right=120),
        _text("Ready", 1, 143, 40, right=166),
        _text("02", 1, 20, 60, right=30),
        _text("Remote", 1, 100, 60, right=130),
        _text("Failed", 1, 143, 60, right=170),
    ]}), encoding="utf-8")
    rows = build_code_table_chunks_from_docling_json(path)
    assert rows[0]["column_values"] == [
        {"column": "Code", "value": "01"},
        {"column": "Source", "value": "Local"},
        {"column": "Status", "value": "Ready"},
    ]


def test_docling_ambiguous_header_does_not_invent_column_names(tmp_path):
    path = tmp_path / "ambiguous.json"
    path.write_text(json.dumps({"texts": [
        _text("Table 2 - Result Codes", 1, 20, 10, "caption"),
        _text("Code", 1, 20, 20, right=45),
        _text("Unclear", 1, 100, 20, right=210),
        _text("Status", 1, 180, 20, right=220),
        _text("01", 1, 20, 40), _text("Local", 1, 100, 40),
        _text("Ready", 1, 180, 40),
        _text("02", 1, 20, 60), _text("Remote", 1, 100, 60),
    ]}), encoding="utf-8")
    rows = build_code_table_chunks_from_docling_json(path)
    assert all(row["column_alignment"] == "uncertain" for row in rows)
    assert all(row["column_values"] == [] for row in rows)
    assert "不能按非空值顺序推断列含义" in rows[0]["content"]


def test_docling_merged_body_cell_does_not_shift_other_rows(tmp_path):
    path = tmp_path / "merged_body.json"
    path.write_text(json.dumps({"texts": [
        _text("Table 2 - Result Codes", 1, 20, 10, "caption"),
        _text("Code", 1, 20, 20, right=45),
        _text("Definition", 1, 100, 20, right=150),
        _text("Flag", 1, 180, 20, right=205),
        _text("01", 1, 20, 40, right=30),
        _text("Approved Yes", 1, 100, 40, right=207),
        _text("02", 1, 20, 60, right=30),
        _text("Declined", 1, 100, 60, right=150),
        _text("No", 1, 180, 60, right=195),
    ]}), encoding="utf-8")
    rows = build_code_table_chunks_from_docling_json(path)
    assert rows[0]["column_alignment"] == "uncertain"
    assert rows[1]["column_alignment"] == "recovered"
    assert "Flag: No" in rows[1]["content"]


def test_table_resume_replaces_old_row_without_duplicate_or_stale_vector():
    old = {
        "id": "doc-chunk-4", "chunk_order_index": 4, "modality": "table_row",
        "table_name": "Table 2 - Result Codes", "page_no": 1, "code_value": "01",
        "content": "[代码表行] old flat text", "vector": [0.1], "search_text": "old",
    }
    new = {**old, "content": "[代码表行] Flag: 原表空白（未给值） | Category: 1"}
    new.pop("id")
    new.pop("chunk_order_index")
    chunks = [{"content": "untouched正文", "chunk_order_index": 0}, old]
    assert merge_derived_table_chunks(chunks, [new]) == (0, 1)
    assert len(chunks) == 2
    assert chunks[0]["content"] == "untouched正文"
    assert chunks[1]["id"] == "doc-chunk-4" and chunks[1]["chunk_order_index"] == 4
    assert chunks[1]["content"] == new["content"]
    assert "vector" not in chunks[1] and "search_text" not in chunks[1]
    assert merge_derived_table_chunks(chunks, [new]) == (0, 0)


def test_table_resume_only_appends_missing_rows_and_keeps_ambiguous_identity():
    row = {"modality": "table_row", "table_name": "Table 2", "page_no": 1,
           "code_value": "01", "content": "[代码表行] existing"}
    chunks = [{**row, "id": "a"}, {**row, "id": "b", "content": "[代码表行] other"}]
    derived = [{**row, "content": "[代码表行] new version"},
               {**row, "code_value": "02", "content": "[代码表行] missing"}]
    assert merge_derived_table_chunks(chunks, derived) == (1, 0)
    assert [c.get("id") for c in chunks[:2]] == ["a", "b"]
    assert [c["chunk_order_index"] for c in chunks[2:]] == [2]
    assert merge_derived_table_chunks(chunks, derived) == (0, 0)


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
