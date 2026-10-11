"""Independent baseline/candidate RAG runs. Never enables a running worker.

Run from the server repository. This uses existing model APIs and SELECT/search
paths, suppresses LLMCallLog insertion in this process, and forbids creating the
main Milvus collection. Reports go to the requested folder; ordinary framework
logs may also be emitted by the existing application logger.
Default cases are NEW conversations, not historical multi-turn reproduction.
"""
import argparse
import asyncio
import copy
import hashlib
import inspect
import json
import sys
import time
from pathlib import Path


CASES = [
    ("visa_f56_max", "VISA F56最大长度是多少"),
    ("visa_f56_usage", "VISA F56使用场景"),
    ("visa_f63_3", "VISA F63.3的内容和应用是什么"),
    ("visa_reject_0400", "VISA拒绝码0400什么意思"),
    ("visa_response_85", "VISA39域返回85什么意思"),
    ("visa_account_verification", "VISA账户验证的发出报文是什么条件"),
    ("visa_f111", "VISA F111适用于哪些报文类型"),
    ("mc_de56", "万事达DE56是什么"),
    ("mc_de111", "万事达DE111有什么用途"),
]


def snapshot(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def summarize(run):
    raw = run.get("raw_data") or {}
    chunks = (raw.get("data") or {}).get("chunks") or []
    metadata = raw.get("metadata") or {}
    events = run.get("rerank_events") or []
    return {
        "error": run.get("error"),
        "resolved_query": metadata.get("resolved_query"),
        "rewritten_query": metadata.get("rewritten_query"),
        "english_query": metadata.get("english_query"),
        "candidate_count": metadata.get("total_chunks_found"),
        "final_count": len(chunks),
        "final_files": sorted({str(c.get("file_name")) for c in chunks}),
        "rerank": [{
            "query": event.get("query"),
            "input_count": len(event.get("input_chunks") or []),
            "output_count": event.get("output_count"),
            "output_with_rerank_score": event.get("output_with_rerank_score"),
            "api_returned_counts": [len(call.get("results") or [])
                                    for call in event.get("api_calls", [])],
            "status": event.get("status"),
        } for event in events],
        # A source-match indicator only. It does not judge answer correctness.
        "visa_f56_attributes_in_final": any(
            "Field 56" in str(c.get("content", ""))
            and "1537" in str(c.get("content", ""))
            and "visa" in str(c.get("file_name", "")).lower()
            for c in chunks),
    }


def save_report(folder, report):
    target = folder / "report.json"
    pending = folder / "report.json.tmp"
    pending.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(target)
    lines = ["# 原流程 / 候选流程配对结果", "",
             "线上开关未开启；单次配对不等于正确率回归通过。",
             "默认各题均为新对话；历史问答需另外提供相同完整上下文。", ""]
    for item in report["cases"]:
        lines.extend(["## " + item["question"], ""])
        for name, label in (("baseline", "原流程"), ("candidate", "候选流程")):
            run = item.get(name)
            if run is None:
                continue
            lines.extend(["### " + label, "",
                          "```json", json.dumps(summarize(run), ensure_ascii=False, indent=2),
                          "```", "", run.get("answer") or run.get("context") or "未生成答案", ""])
    (folder / "summary.md").write_text("\n".join(lines), encoding="utf-8")


async def execute(args):
    repo = Path(args.repo).resolve()
    sys.path.insert(0, str(repo))
    if Path.cwd().resolve() != repo:
        raise RuntimeError("请先 cd 到服务器实际运行的项目目录。")
    from configure import PROJECT_CONFIG as cfg
    from configure.project_config import TORTOISE_ORM
    from tortoise import Tortoise
    from applications.jiayueyang.rag import query as qm
    from applications.jiayueyang.rag import query_rewriter as rw
    from applications.jiayueyang.rag import rerank as rm
    from applications.jiayueyang.rag import llm, milvus_store as ms

    if bool(getattr(cfg, "RAG_FIELD_ALIASES_ENABLED", False)):
        raise RuntimeError("线上配置已开启。此脚本要求先保留关闭状态，不能跳过原流程对照。")
    if "enable_field_aliases" not in inspect.signature(rw.rewrite_query_bilingual).parameters:
        raise RuntimeError("此目录未安装候选补丁。")
    source = Path(rw.__file__).read_text(encoding="utf-8")
    if "bilingual:field-alias-v2:" not in source:
        raise RuntimeError("请先完成子字段重叠修正，避免把 F63.3 误提取成 F63。")

    cases = [{"id": key, "question": question, "history": []} for key, question in CASES]
    if args.cases:
        loaded = json.loads(Path(args.cases).read_text(encoding="utf-8"))
        cases = loaded["cases"] if isinstance(loaded, dict) else loaded
        for case in cases:
            if "history" not in case:
                if case.get("prior_questions"):
                    raise RuntimeError("多轮案例需 history 完整消息，不能只用 prior_questions 标题。")
                case["history"] = []
    if args.ids:
        wanted = set(args.ids.split(","))
        available = {case["id"] for case in cases}
        if wanted - available:
            raise RuntimeError("未知案例 ID: " + str(sorted(wanted - available)))
        cases = [case for case in cases if case["id"] in wanted]

    folder = Path(args.out).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    report = {
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "repo": str(repo), "rewriter_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "online_flag_at_start": False,
        "model": args.model or cfg.LLM_MODEL,
        "rerank_model": cfg.RERANK_MODEL,
        "rerank_min_score": cfg.RERANK_MIN_SCORE,
        "rerank_chunking": cfg.RERANK_ENABLE_CHUNKING,
        "settings": {key: getattr(cfg, key, None) for key in
                     ("CHUNK_TOP_K", "RRF_TOP_K", "MAX_TOTAL_TOKENS", "DOC_RECALL_ENABLED")},
        "notes": ["No online reload or .env change.",
                  "Single paired run; answer facts require source review.",
                  "Raw rerank indices refer to api_calls.documents, including any subdocuments."],
        "cases": [],
    }
    save_report(folder, report)
    print("线上保持关闭；测试模型:", report["model"], "重排阈值:", cfg.RERANK_MIN_SCORE, flush=True)
    print("报告目录:", folder, "；将逐题保存，耗时取决于模型服务。", flush=True)

    original_flag = cfg.RAG_FIELD_ALIASES_ENABLED
    original_rerank, original_api = qm.rerank_chunks, rm._rerank_api
    original_ensure, original_persist = ms._ensure_collection, llm._spawn_persist
    active = {"run": None, "event": None}

    def existing_collection_only(client):
        if not client.has_collection(ms._COLLECTION_NAME):
            raise RuntimeError("现有 Milvus 集合不存在；测试禁止创建或重建。")
        return original_ensure(client)

    async def traced_api(query, documents, top_n=None):
        call = {"query": query, "documents": snapshot(documents), "top_n": top_n}
        if active["event"] is not None:
            active["event"]["api_calls"].append(call)
        try:
            result = await original_api(query, documents, top_n=top_n)
            call["results"] = snapshot(result)
            return result
        except BaseException as exc:
            call["error"] = type(exc).__name__ + ": " + str(exc)[:300]
            raise

    async def traced_rerank(query, chunks, top_n=None):
        event = {"query": query, "input_chunks": snapshot(chunks), "api_calls": []}
        active["run"]["rerank_events"].append(event)
        previous = active["event"]
        active["event"] = event
        try:
            result = await original_rerank(query, chunks, top_n=top_n)
            event["output_count"] = len(result)
            event["output_with_rerank_score"] = sum("rerank_score" in c for c in result)
            event["output_chunks"] = snapshot(result)
            event["status"] = "returned"
            return result
        except BaseException as exc:
            event["status"] = type(exc).__name__
            raise
        finally:
            active["event"] = previous

    # These overrides exist only in this test process; worker configuration is untouched.
    ms._ensure_collection = existing_collection_only
    llm._spawn_persist = lambda **kwargs: None
    qm.rerank_chunks, rm._rerank_api = traced_rerank, traced_api
    try:
        await asyncio.wait_for(Tortoise.init(config=TORTOISE_ORM), timeout=30)
        for index, case in enumerate(cases, 1):
            item = {"id": case["id"], "question": case["question"],
                    "history": copy.deepcopy(case["history"])}
            report["cases"].append(item)
            for name, candidate in (("baseline", False), ("candidate", True)):
                run = {"rerank_events": []}
                item[name], active["run"] = run, run
                cfg.RAG_FIELD_ALIASES_ENABLED = candidate
                started = time.monotonic()
                print(f"[{index}/{len(cases)}] {case['question']} / {name} 开始", flush=True)
                try:
                    params = qm.QueryParam(
                        mode="hybrid", stream=False, enable_rerank=True,
                        only_need_context=False, model=args.model,
                        conversation_history=copy.deepcopy(case["history"]),
                        conversation_summary=case.get("conversation_summary", ""),
                        conversation_recall=case.get("conversation_recall", ""),
                    )
                    result = await asyncio.wait_for(qm.hybrid_query(case["question"], params),
                                                    timeout=args.timeout)
                    run["raw_data"] = snapshot(result.raw_data)
                    run["answer"] = result.content
                except Exception as exc:
                    run["error"] = type(exc).__name__ + ": " + str(exc)[:500]
                finally:
                    cfg.RAG_FIELD_ALIASES_ENABLED = original_flag
                    run["elapsed_seconds"] = round(time.monotonic() - started, 1)
                    save_report(folder, report)
                info = summarize(run)
                counts = [(event.get("input_count"), event.get("output_with_rerank_score"))
                          for event in info["rerank"]]
                print("  完成: 最终分块=", info["final_count"],
                      "重排(输入数,返回中有重排分数的数量)=", counts,
                      "F56长度证据=", info["visa_f56_attributes_in_final"],
                      "错误=", info["error"], flush=True)
        report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        print("结果已保存。请审查答案和 PDF；本脚本不会自动宣布回归通过。", flush=True)
    finally:
        cfg.RAG_FIELD_ALIASES_ENABLED = original_flag
        qm.rerank_chunks, rm._rerank_api = original_rerank, original_api
        ms._ensure_collection, llm._spawn_persist = original_ensure, original_persist
        save_report(folder, report)
        await Tortoise.close_connections()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path.cwd()))
    parser.add_argument("--out", required=True, help="New output directory, never overwrite old results")
    parser.add_argument("--model", help="Use the same selected generation model as the UI")
    parser.add_argument("--ids", help="Optional comma-separated case IDs")
    parser.add_argument("--cases", help="JSON cases with question and optional full history messages")
    parser.add_argument("--timeout", type=int, default=240, help="Seconds per individual run")
    args = parser.parse_args()
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
