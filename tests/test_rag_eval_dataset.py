import json
from pathlib import Path


def test_eval_cases_have_stable_knowledge_boundary():
    path = Path(__file__).parent / "fixtures" / "rag_eval_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert cases
    ids = [item["id"] for item in cases]
    assert len(ids) == len(set(ids))
    for item in cases:
        assert isinstance(item["expect_in_kb"], bool)
        assert item["question"]
        if item["expect_in_kb"]:
            assert item.get("expected_points")
        else:
            assert item.get("expected_behavior")
