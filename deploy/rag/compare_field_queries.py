"""Compare query preparation only; never toggle online config or change stored documents."""
import asyncio
import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from configure import PROJECT_CONFIG
from applications.jiayueyang.rag.query_rewriter import rewrite_query_bilingual

QUERIES = ["VISA F56最大长度是多少", "VISA F56使用场景",
           "VISA F63.3的内容和应用是什么", "VISA拒绝码0400什么意思",
           "万事达DE56是什么", "万事达DE111有什么用途"]
async def main():
    if "enable_field_aliases" not in inspect.signature(rewrite_query_bilingual).parameters:
        raise RuntimeError("Candidate function not installed in this working directory.")
    enabled = bool(getattr(PROJECT_CONFIG, "RAG_FIELD_ALIASES_ENABLED", False))
    print("在线配置:", enabled, "（应为False；此脚本不修改配置）", flush=True)
    if enabled:
        raise RuntimeError("Online flag is enabled; capture baseline with flag disabled first.")
    results = []
    for query in QUERIES:
        item = dict(question=query)
        print("\n原问题:", query, flush=True)
        for name, candidate in (("原流程", False), ("候选流程", True)):
            try:
                result = await asyncio.wait_for(
                    rewrite_query_bilingual(query, enable_field_aliases=candidate), timeout=60)
                values = dict(primary=result.primary_query, english=result.english_query,
                              identifiers=list(result.identifiers), rerank_query=result.rerank_query)
                print(name, json.dumps(values, ensure_ascii=False), flush=True)
                item[name] = values
            except Exception as exc:
                item[name] = dict(error_type=type(exc).__name__, error=str(exc)[:180])
                print(name, item[name], flush=True)
        results.append(item)
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/field-alias-query-pairs.json")
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n输出:", output, "\n这仅比较查询准备，不代表召回或答案正确率回归通过。", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
