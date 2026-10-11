"""Offline safety/trace tests. They do NOT validate bank retrieval or answers."""
import argparse
import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from deploy.rag import compare_rag_evidence as runner


class RunnerTests(unittest.TestCase):
    def make_environment(self, root, online=False, present=True, fail_candidate=False):
        cfg = types.SimpleNamespace(RAG_FIELD_ALIASES_ENABLED=online, LLM_MODEL="fake",
                                    RERANK_MODEL="fake", RERANK_MIN_SCORE=.5,
                                    RERANK_ENABLE_CHUNKING=False)
        configure = types.ModuleType("configure")
        configure.PROJECT_CONFIG = cfg
        configmod = types.ModuleType("configure.project_config")
        configmod.TORTOISE_ORM = {}
        db_events, ensure_events = [], []

        class FakeDB:
            @staticmethod
            async def init(**kwargs):
                db_events.append("init")

            @staticmethod
            async def close_connections():
                db_events.append("close")

        tortoise = types.ModuleType("tortoise")
        tortoise.Tortoise = FakeDB
        packages = {}
        for name in ("applications", "applications.jiayueyang", "applications.jiayueyang.rag"):
            packages[name] = types.ModuleType(name)
            packages[name].__path__ = []
        rag = packages["applications.jiayueyang.rag"]
        for name in ("query", "query_rewriter", "rerank", "llm", "milvus_store"):
            module = types.ModuleType("applications.jiayueyang.rag." + name)
            setattr(rag, name, module)
            packages[module.__name__] = module
        rw, rm, qm, ms = rag.query_rewriter, rag.rerank, rag.query, rag.milvus_store
        path = root / "rewriter.py"
        path.write_text("# bilingual:field-alias-v2:\n", encoding="utf-8")
        rw.__file__ = str(path)

        async def rewrite(query, enable_field_aliases=None):
            pass

        rw.rewrite_query_bilingual = rewrite
        ms._COLLECTION_NAME = "existing"

        def ensure(client):
            ensure_events.append("checked")

        ms._ensure_collection = ensure
        rag.llm._spawn_persist = lambda **kwargs: db_events.append("persist")

        async def api(query, documents, top_n=None):
            return [{"index": 0, "relevance_score": .95 if cfg.RAG_FIELD_ALIASES_ENABLED else .1}]

        async def rerank(query, chunks, top_n=None):
            result = await rm._rerank_api(query, [c["content"] for c in chunks], top_n=top_n)
            return [{**chunks[0], "rerank_score": result[0]["relevance_score"]}] if result[0]["relevance_score"] >= .5 else chunks

        rm._rerank_api, qm.rerank_chunks = api, rerank
        qm.QueryParam = types.SimpleNamespace

        async def hybrid(query, params):
            ms._ensure_collection(types.SimpleNamespace(has_collection=lambda name: present))
            rag.llm._spawn_persist(test=True)
            if fail_candidate and cfg.RAG_FIELD_ALIASES_ENABLED:
                raise RuntimeError("candidate failed")
            chunks = [{"content": "Field 56 maximum 1537", "file_name": "VISA.pdf"}]
            chunks = await qm.rerank_chunks(query, chunks, top_n=50)
            return types.SimpleNamespace(content="fake answer", raw_data={
                "data": {"chunks": chunks}, "metadata": {"total_chunks_found": 1}})

        qm.hybrid_query = hybrid
        modules = {"configure": configure, "configure.project_config": configmod,
                   "tortoise": tortoise, **packages}
        originals = (qm.rerank_chunks, rm._rerank_api, ms._ensure_collection, rag.llm._spawn_persist)
        args = argparse.Namespace(repo=str(Path.cwd()), out=str(root / "results"),
                                  cases=None, ids="visa_f56_max", model=None, timeout=1)
        return cfg, modules, args, db_events, ensure_events, originals, rag

    def run_fake(self, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            cfg, modules, args, db, ensures, originals, rag = self.make_environment(Path(directory), **kwargs)
            with patch.dict(sys.modules, modules), patch("builtins.print"):
                asyncio.run(runner.execute(args))
            report = json.loads((Path(args.out) / "report.json").read_text(encoding="utf-8"))
            self.assertFalse(cfg.RAG_FIELD_ALIASES_ENABLED)
            self.assertEqual((rag.query.rerank_chunks, rag.rerank._rerank_api,
                              rag.milvus_store._ensure_collection, rag.llm._spawn_persist), originals)
            self.assertEqual(db, ["init", "close"])
            return report, ensures

    def test_pair_traces_actual_fallback_and_score_and_restores(self):
        report, ensures = self.run_fake()
        case = report["cases"][0]
        self.assertEqual(ensures, ["checked", "checked"])
        self.assertEqual(runner.summarize(case["baseline"])["rerank"][0]["output_with_rerank_score"], 0)
        self.assertEqual(runner.summarize(case["candidate"])["rerank"][0]["output_with_rerank_score"], 1)
        self.assertEqual(case["candidate"]["rerank_events"][0]["api_calls"][0]["results"][0]["relevance_score"], .95)

    def test_failed_candidate_keeps_baseline_and_restores(self):
        report, _ = self.run_fake(fail_candidate=True)
        self.assertEqual(report["cases"][0]["baseline"]["answer"], "fake answer")
        self.assertIn("candidate failed", report["cases"][0]["candidate"]["error"])

    def test_missing_collection_never_calls_creation_capable_ensure(self):
        report, ensures = self.run_fake(present=False)
        self.assertEqual(ensures, [])
        self.assertIn("禁止创建", report["cases"][0]["baseline"]["error"])

    def test_enabled_online_flag_fails_before_testing(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg, modules, args, db, _, originals, rag = self.make_environment(Path(directory), online=True)
            with patch.dict(sys.modules, modules), self.assertRaisesRegex(RuntimeError, "线上配置已开启"):
                asyncio.run(runner.execute(args))
            self.assertTrue(cfg.RAG_FIELD_ALIASES_ENABLED)
            self.assertEqual(db, [])
            self.assertFalse(Path(args.out).exists())
            self.assertIs(rag.query.rerank_chunks, originals[0])


if __name__ == "__main__":
    unittest.main()
