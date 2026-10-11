"""Synthetic checks of the review gate, not tests of bank answers."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "deploy/rag"
SPEC = json.loads((ROOT / "regression_cases.json").read_text(encoding="utf-8"))

class ReviewGateChecks(unittest.TestCase):
    def fixture(self):
        records = []
        for case in SPEC["cases"]:
            old_score = case["screenshot_score"]
            old_score = old_score if old_score is not None else 8
            n = len(case["required_facts"])
            before = dict(score=old_score, facts=[old_score > 6] * n,
                          critical_errors=int(old_score <= 6), citations_checked=True,
                          evidence_recall=0.5, trace="synthetic-before")
            after = dict(score=max(8.5, old_score), facts=[True] * n,
                         critical_errors=0, citations_checked=True,
                         evidence_recall=1, trace="synthetic-after")
            records.append(dict(id=case["id"], before=before, after=after))
        return dict(cases=records)

    def run_gate(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return subprocess.run([sys.executable, str(ROOT / "check_regression_gate.py"), str(path)],
                                  capture_output=True, text=True, encoding="utf-8")

    def test_pending_results_never_pass(self):
        data = self.fixture()
        data["cases"][0]["after"] = None
        result = self.run_gate(data)
        self.assertEqual(result.returncode, 2)
        self.assertIn("paired review missing", result.stdout)

    def test_complete_improvements_pass(self):
        self.assertEqual(self.run_gate(self.fixture()).returncode, 0)

    def test_higher_score_cannot_hide_loss_of_correct_fact(self):
        data = self.fixture()
        data["cases"][0]["after"]["score"] = 10
        data["cases"][0]["after"]["facts"][0] = False
        result = self.run_gate(data)
        self.assertEqual(result.returncode, 2)
        self.assertIn("previously correct fact lost", result.stdout)

    def test_score_and_evidence_regression_rejected(self):
        for field, value, message in [("score", 8, "answer score regressed"),
                                      ("evidence_recall", 0.25, "evidence coverage regressed")]:
            with self.subTest(field=field):
                data = self.fixture()
                data["cases"][0]["after"][field] = value
                result = self.run_gate(data)
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stdout)

    def test_new_critical_error_rejected(self):
        data = self.fixture()
        data["cases"][0]["after"]["critical_errors"] = 1
        result = self.run_gate(data)
        self.assertEqual(result.returncode, 2)
        self.assertIn("candidate has errors", result.stdout)

if __name__ == "__main__":
    unittest.main(verbosity=2)
