"""Offline checks for field aliases and the bilingual query flow; no service calls."""
import ast
import asyncio
import json
import re
import sys
import time
import unittest
from unittest.mock import patch
from types import ModuleType
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "applications/jiayueyang/rag/query_rewriter.py"
BASELINE = ROOT / "tests/fixtures/query_rewriter_disabled_baseline.json"


def load_patch_functions(source_text=None):
    names = {
        "_FIELD_ALIAS_RE", "_FIELD_IDENTIFIER_RE", "_IDENTIFIER_RE",
        "_CANONICAL_ENGLISH_ALIASES", "_normalize_field_aliases", "_extract_identifiers",
        "_append_missing_identifiers", "_append_canonical_english_aliases",
        "BilingualQuery", "rewrite_query_bilingual", "_ENGLISH_QUERY_PROMPT",
        "_llm_translate_query", "_clean_markers",
    }
    tree = ast.parse(source_text if source_text is not None else SOURCE.read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        name = getattr(node, "name", None)
        if isinstance(node, ast.Assign):
            name = getattr(node.targets[0], "id", None)
        elif isinstance(node, ast.AnnAssign):
            name = getattr(node.target, "id", None)
        if name in names:
            body.append(node)
    namespace = {}
    exec("from dataclasses import dataclass\nfrom typing import *\n", namespace)
    namespace.update(re=re, json=json, _time=time, PROJECT_CONFIG=SimpleNamespace(RAG_FIELD_ALIASES_ENABLED=False))
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


class FieldAliasChecks(unittest.TestCase):
    def setUp(self):
        self.ns = load_patch_functions()

    def test_aliases_adjacent_to_chinese_and_subfields(self):
        norm = self.ns["_normalize_field_aliases"]
        cases = {
            "VISA F56使用场景": "VISA Field 56使用场景",
            "VISA F111适用于哪些报文": "VISA Field 111适用于哪些报文",
            "F63.3内容和应用": "Field 63.3内容和应用",
            "F34 DF1F值为7.5": "Field 34 DF1F值为7.5",
            "查询f 56，及F39返回85": "查询Field 56，及Field 39返回85",
        }
        for before, after in cases.items():
            with self.subTest(before=before):
                self.assertEqual(norm(before), after)
                self.assertEqual(norm(after), after)

    def test_preserve_other_identifiers_and_values(self):
        norm = self.ns["_normalize_field_aliases"]
        for value in ["DF1F", "F1F", "0xF56", "/api/F56/test", "F56/test",
                      "read_F56_file", "spec-F56", "F1234", "DE56", "7.5", "0400"]:
            with self.subTest(value=value):
                self.assertEqual(norm(value), value)

    def test_identifier_preservation_in_chinese_queries(self):
        extract = self.ns["_extract_identifiers"]
        self.assertEqual(extract("VISA F56使用场景", "VISA Field 56使用场景", enable_field_aliases=True), ("Field 56",))
        self.assertIn("Field 63.3", extract("F63.3的内容", enable_field_aliases=True))
        self.assertIn("DE111", extract("万事达DE111用途", enable_field_aliases=True))
        self.assertIn("DF1F", extract("F34 DF1F", enable_field_aliases=True))
        self.assertIn("/api/F56/test", extract("检查 /api/F56/test", enable_field_aliases=True))

    def test_subfield_does_not_invent_parent_but_preserves_explicit_parent(self):
        extract = self.ns["_extract_identifiers"]
        for query, expected in [
            ("VISA F63.3的内容和应用是什么", ("Field 63.3",)),
            ("VISA Field 63.3的内容", ("Field 63.3",)),
            ("VISA F126.10怎么使用", ("Field 126.10",)),
            ("万事达DE48.1的说明", ("DE48.1",)),
            ("VISA F63.3的内容，F63整体是什么", ("Field 63.3", "Field 63")),
            ("VISA F63.3，标签 DF1F", ("Field 63.3", "DF1F")),
        ]:
            with self.subTest(query=query):
                self.assertEqual(extract(query, enable_field_aliases=True), expected)

    def prepare_flow(self, translate_fails=False, ns=None, passthrough=False):
        ns = ns if ns is not None else self.ns
        seen = []

        async def rewrite(query, **kwargs):
            seen.append(query)
            return query if passthrough else "VISA F56最大长度是多少"

        async def translate(query):
            if translate_fails:
                raise RuntimeError("controlled translation failure")
            return query if passthrough else "VISA F56 maximum length"

        ns.update(
            _bilingual_cache={}, _cache_times={}, _cache_ttl=3600,
            _cache_key=lambda query, docs: (query, docs),
            rewrite_query=rewrite, _llm_translate_query=translate,
            _append_deterministic_mapping_terms=lambda query, hints: query,
            _append_deterministic_mapping_english=lambda query, hints: query,
            LOGGER=SimpleNamespace(info=lambda *args: None, warning=lambda *args: None),
        )
        return seen

    def test_normalizes_before_and_after_models_keeps_original_and_uses_cache(self):
        seen = self.prepare_flow()
        ns = self.ns
        query = "VISA F56最大长度是多少"
        old_key = ns["_cache_key"]('bilingual:' + query + '|mapping:[]', frozenset())
        ns["_bilingual_cache"][old_key] = object()
        ns["_cache_times"][old_key] = time.time()
        result = asyncio.run(ns["rewrite_query_bilingual"](query, enable_field_aliases=True))
        self.assertEqual(seen, ["VISA Field 56最大长度是多少"])
        self.assertEqual(result.original_query, query)
        self.assertEqual(result.primary_query, "VISA Field 56最大长度是多少")
        self.assertEqual(result.english_query, "VISA Field 56 maximum length")
        self.assertEqual(result.identifiers, ("Field 56",))
        self.assertNotIn("F56", result.rerank_query)
        self.assertIs(asyncio.run(ns["rewrite_query_bilingual"](query, enable_field_aliases=True)), result)
        self.assertEqual(len(seen), 1)

    def test_translation_failure_keeps_canonical_field(self):
        self.prepare_flow(translate_fails=True)
        result = asyncio.run(self.ns["rewrite_query_bilingual"]("VISA F56最大长度是多少", enable_field_aliases=True))
        self.assertEqual(result.primary_query, "VISA Field 56最大长度是多少")
        self.assertEqual(result.english_query, "")
        self.assertEqual(result.identifiers, ("Field 56",))

    def result_values(self, result):
        return [result.original_query, result.primary_query, result.english_query,
                list(result.identifiers), result.rerank_query]

    def test_disabled_flow_equals_frozen_baseline(self):
        samples = json.loads(BASELINE.read_text(encoding="utf-8"))["cases"]
        for sample in samples:
            with self.subTest(query=sample["question"], translation_fails=sample["translation_fails"]):
                ns = self.ns
                seen = self.prepare_flow(sample["translation_fails"], passthrough=True)
                ns["_cache_key"] = lambda query, docs: query
                result = asyncio.run(ns["rewrite_query_bilingual"](
                    sample["question"], doc_ids=frozenset({"visa", "mc"}),
                    mapping_matches=[{"term": "fixed"}],
                ))
                self.assertEqual(seen, sample["rewrite_inputs"])
                self.assertEqual(self.result_values(result), sample["result"])
                self.assertEqual(list(ns["_bilingual_cache"]), sample["cache_keys"])

    def test_default_reads_existing_cache_and_enabled_cache_is_independent(self):
        seen = self.prepare_flow()
        ns = self.ns
        query = "VISA F56最大长度是多少"
        key = ns["_cache_key"]('bilingual:' + query + '|mapping:[]', frozenset())
        legacy_value = object()
        ns["_bilingual_cache"][key] = legacy_value
        ns["_cache_times"][key] = time.time()
        self.assertIs(asyncio.run(ns["rewrite_query_bilingual"](query)), legacy_value)
        candidate = asyncio.run(ns["rewrite_query_bilingual"](query, enable_field_aliases=True))
        self.assertEqual(candidate.identifiers, ("Field 56",))
        self.assertIs(asyncio.run(ns["rewrite_query_bilingual"](query)), legacy_value)
        self.assertEqual(len(seen), 1)

    def test_enabled_preserves_good_queries_without_f_aliases(self):
        for query in ["VISA拒绝码0400什么意思", "VISA39域返回85什么意思",
                      "VISA账户验证的发出报文是什么条件", "万事达DE56用途"]:
            with self.subTest(query=query):
                ns = self.ns
                self.prepare_flow(passthrough=True)
                before = asyncio.run(ns["rewrite_query_bilingual"](query))
                after = asyncio.run(ns["rewrite_query_bilingual"](query, enable_field_aliases=True))
                # Compare values, not evidence accuracy; real model and server tests are separate.
                self.assertEqual(before.primary_query, after.primary_query)
                self.assertEqual(before.english_query, after.english_query)

    def test_config_switch_and_explicit_override(self):
        self.prepare_flow()
        ns = self.ns
        ns["PROJECT_CONFIG"].RAG_FIELD_ALIASES_ENABLED = True
        candidate = asyncio.run(ns["rewrite_query_bilingual"]("VISA F56最大长度是多少"))
        self.assertEqual(candidate.identifiers, ("Field 56",))
        baseline = asyncio.run(ns["rewrite_query_bilingual"]("VISA F56最大长度是多少", enable_field_aliases=False))
        self.assertEqual(baseline.primary_query, "VISA F56最大长度是多少")
        self.assertEqual(baseline.identifiers, ())

    def test_english_query_budget_matches_server_and_keeps_output_cleaning(self):
        calls = []

        async def chat_completion(**kwargs):
            calls.append(kwargs)
            return "English retrieval query: VISA Field 56 maximum length\nignored second line"

        module = ModuleType("applications.jiayueyang.rag.llm")
        module.chat_completion = chat_completion
        with patch.dict(sys.modules, {module.__name__: module}):
            result = asyncio.run(self.ns["_llm_translate_query"]("VISA Field 56最大长度是多少"))
        self.assertEqual(result, "VISA Field 56 maximum length")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["max_tokens"], 1024)
        self.assertFalse(calls[0]["stream"])
        self.assertEqual(calls[0]["temperature"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
