"""Validate human-reviewed paired results. Never infer answer quality from rerank scores."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
spec = json.loads((root / "regression_cases.json").read_text(encoding="utf-8"))
path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "regression_review_template.json"
records = json.loads(path.read_text(encoding="utf-8"))["cases"]
by_id = {r["id"]: r for r in records}
failures = []
if len(by_id) != len(records):
    failures.append("duplicate case ids")
for case in spec["cases"]:
    label = case["id"]
    record = by_id.get(label, {})
    before, after = record.get("before"), record.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        failures.append(label + ": paired review missing")
        continue
    expected = len(case["required_facts"])
    valid = True
    for name, item in (("before", before), ("after", after)):
        score = item.get("score")
        facts = item.get("facts")
        if (type(score) not in (int, float) or not 0 <= score <= 10
                or not isinstance(facts, list) or len(facts) != expected
                or any(type(f) is not bool for f in facts)
                or type(item.get("critical_errors")) is not int
                or item["critical_errors"] < 0
                or item.get("citations_checked") is not True
                or type(item.get("evidence_recall")) not in (int, float)
                or not 0 <= item["evidence_recall"] <= 1
                or not isinstance(item.get("trace"), str) or not item["trace"].strip()):
            failures.append(label + ": incomplete " + name + " source review")
            valid = False
    if not valid:
        continue
    if after["score"] < before["score"]:
        failures.append(label + ": answer score regressed")
    if any(old and not new for old, new in zip(before["facts"], after["facts"])):
        failures.append(label + ": previously correct fact lost")
    if after["evidence_recall"] < before["evidence_recall"]:
        failures.append(label + ": evidence coverage regressed")
    if after["critical_errors"] or not all(after["facts"]):
        failures.append(label + ": candidate has errors or missing required facts")
    if case["category"] == "修复失败" and after["score"] < 7:
        failures.append(label + ": failed answer not sufficiently repaired")
if failures:
    print("NOT ACCEPTED / 尚不能上线")
    for failure in failures:
        print("-", failure)
    sys.exit(2)
print("REVIEW GATE PASSED / 当前样本通过人工回归；不代表所有未来问题必然正确")
