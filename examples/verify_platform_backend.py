"""真实 HTTP 联调验证；只向显式指定的本机服务写入合成样例，不打印 token。"""
import argparse
import base64
import io
import json
from pathlib import Path
import time
import uuid
import zipfile

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8520")
    parser.add_argument("--user-scenarios", action="store_true", help="额外验证批量替换、改名及相同文件重传")
    args = parser.parse_args()
    if not args.url.startswith("http://127.0.0.1:"):
        parser.error("此验证脚本仅允许本机合成数据联调")
    base, session = args.url.rstrip("/"), requests.Session()
    def call(method, path, **kwargs):
        response = session.request(method, base + path, timeout=30, **kwargs)
        response.raise_for_status()
        result = response.json()
        if result.get("status") != "success":
            raise AssertionError(result.get("message", "业务请求失败"))
        return result["data"]
    health = session.get(base + "/health", timeout=5).json()
    auth = call("POST", "/base/auth/access_token", json={"username": "skill-dev", "password": "SkillLocal2026!"})
    session.headers["token"] = auth["access_token"]
    run_id = uuid.uuid4().hex[:8]
    knowledge_source = {"knowledge_name": f"后端联调转账规则-{run_id}", "description": "纯合成的后端知识库联调样例",
        "tag": "custom", "application": "核心系统", "is_public": False}
    knowledge = call("POST", "/knowledge-bases/", data={"source": json.dumps(knowledge_source)},
        files=[("files", ("rules.md", "# 转账规则\n\n金额必须大于零；余额不足时拒绝转账。".encode())),
               ("files", ("input.txt", "请求必须包含账户和交易金额。".encode()))])
    kb_id = knowledge["id"]
    def complete():
        for _ in range(120):
            current = call("GET", f"/knowledge-bases/{kb_id}")
            if current["status"] == "failed":
                raise AssertionError("知识库处理失败，请检查本机服务日志；脚本不会输出模型密钥")
            if current["status"] == "completed":
                return current
            time.sleep(1)
        raise AssertionError("等待知识库处理超时")
    knowledge = complete()
    print("Knowledge created and indexed:", knowledge["version"], knowledge["document_count"], flush=True)
    before_chunks = call("GET", f"/knowledge-bases/{kb_id}/chunks")
    call("PUT", f"/knowledge-bases/{kb_id}", data={"source": json.dumps({**knowledge_source,
        "description": "补充合成联调描述", "change_summary": "仅修改描述", "expected_version": knowledge["version"]})})
    assert before_chunks == call("GET", f"/knowledge-bases/{kb_id}/chunks")
    knowledge = complete()
    first_doc = next(d for d in knowledge["documents"] if d["filename"] == "rules.md")
    call("PUT", f"/knowledge-bases/{kb_id}/documents/{first_doc['id']}/content", json={
        "content": "# 转账规则\n\n金额必须大于零；余额不足时拒绝转账；重复请求必须保持幂等。",
        "change_summary": "补充幂等规则", "expected_generation": first_doc["generation"]})
    knowledge = complete()
    after_chunks = call("GET", f"/knowledge-bases/{kb_id}/chunks")
    other_before = [c for c in before_chunks if c["document_id"] != first_doc["id"]]
    assert other_before == [c for c in after_chunks if c["document_id"] != first_doc["id"]]
    assert knowledge["version"] == "V1.0.2"
    print("Knowledge metadata/edit/history and document-only reindex verified", flush=True)
    user_scenarios = []
    if args.user_scenarios:
        current_docs = {d["filename"]: d for d in knowledge["documents"]}
        originals = {}
        for name, doc in current_docs.items():
            response = session.get(base + f"/knowledge-bases/{kb_id}/documents/{doc['id']}/download", timeout=30)
            response.raise_for_status()
            originals[name] = response.content
        swapped = {"rules.md": originals["input.txt"], "input.txt": originals["rules.md"]}
        call("PUT", f"/knowledge-bases/{kb_id}", data={"source": json.dumps({**knowledge_source,
            "change_summary": "验证两份文件内容交换", "expected_version": knowledge["version"]})},
            files=[("files", (name, content)) for name, content in swapped.items()])
        knowledge = complete()
        assert knowledge["version"] == "V1.0.3"
        for doc in knowledge["documents"]:
            response = session.get(base + f"/knowledge-bases/{kb_id}/documents/{doc['id']}/download", timeout=30)
            response.raise_for_status()
            assert response.content == swapped[doc["filename"]]
        user_scenarios.append("two_document_content_swap")
        keep_id = next(d["id"] for d in knowledge["documents"] if d["filename"] == "rules.md")
        call("PUT", f"/knowledge-bases/{kb_id}", data={"source": json.dumps({**knowledge_source,
            "change_summary": "验证移除旧文件并以新文件名上传", "expected_version": knowledge["version"],
            "retained_document_ids": [keep_id]})}, files=[("files", ("input-renamed.txt", swapped["input.txt"]))])
        knowledge = complete()
        assert knowledge["version"] == "V1.0.4"
        assert {d["filename"] for d in knowledge["documents"]} == {"rules.md", "input-renamed.txt"}
        assert not knowledge["cleanup_pending"]
        user_scenarios.append("remove_and_reupload_same_content_under_new_name")
        before_same = call("GET", f"/knowledge-bases/{kb_id}/chunks")
        call("PUT", f"/knowledge-bases/{kb_id}", data={"source": json.dumps({**knowledge_source,
            "change_summary": "验证相同文件重传", "expected_version": knowledge["version"]})},
            files=[("files", ("rules.md", swapped["rules.md"]))])
        knowledge = complete()
        assert knowledge["version"] == "V1.0.5"
        assert before_same == call("GET", f"/knowledge-bases/{kb_id}/chunks")
        user_scenarios.append("unchanged_reupload_preserves_existing_index")
        print("User scenarios verified: batch replacement, rename, unchanged reupload", flush=True)
    skill = call("POST", "/skills/", json={"name": f"后端联调测试用例-{run_id}", "is_enabled": False})
    skill_id = skill["id"]
    source = {"skill_id": skill_id, "skill_name": skill["name"], "skill_class_id": "SKILL-CASE-001",
        "description": "根据转账需求和业务规则生成测试用例。", "application": "核心系统",
        "instructions": "读取业务规则，参考流程图，按照模板生成正向、异常和边界用例。",
        "knowledge_base_ids": [], "resource_usage": "使用模板组织输出，图片提供流程信息，脚本供运行端使用。",
        "resource_categories": ["template", "asset", "script"], "compatibility": "Python 3.12"}
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=")
    generated = call("POST", "/skills/form/builds", data={"source": json.dumps(source)}, files=[
        ("files", ("template.md", b"| Title | Steps | Expected |")), ("files", ("flow.png", png)),
        ("files", ("check.py", b"# Runtime executes this script, package builder never does.\n"))])
    assert generated["version"] == "1.0.0"
    with zipfile.ZipFile(io.BytesIO(session.get(base + f"/skills/{skill_id}/builds/{generated['build_id']}/download", timeout=30).content)) as archive:
        assert archive.read(f"{generated['name']}/assets/flow.png") == png
    mounted = call("POST", f"/knowledge-bases/{kb_id}/mounts", json={"skill_ids": [skill_id], "resource_usage": source["resource_usage"] + "生成前读取知识库规则。"})
    assert mounted["items"][0]["status"] == "succeeded"
    built = mounted["items"][0]["build"]
    assert built["version"] == "1.0.1" and len(built["files"]) == 6
    definition = call("GET", f"/skills/{skill_id}/definition")
    edited = call("PUT", f"/skills/{skill_id}/definition", json={"expected_version": definition["version"],
        "markdown": definition["markdown"].replace("正向、异常和边界用例", "正向、异常、边界和幂等用例")})
    assert edited["version"] == "1.0.2"
    raw = session.get(base + f"/skills/{skill_id}/builds/{edited['build_id']}/download", timeout=30)
    raw.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(raw.content)) as archive:
        assert len(archive.namelist()) == 6
        assert "幂等用例" in archive.read(f"{edited['name']}/SKILL.md").decode()
        assert archive.read(f"{edited['name']}/assets/flow.png") == png
    report = {"run_id": run_id, "health": health, "knowledge_id": kb_id, "knowledge_version": knowledge["version"],
        "knowledge_document_count": knowledge["document_count"], "knowledge_chunk_count": len(after_chunks),
        "metadata_edit_preserved_chunks": True, "document_edit_only_reindexed_changed_document": True,
        "skill_id": skill_id, "skill_version": edited["version"], "build_id": edited["build_id"],
        "zip_file_count": 6, "zip_image_bytes_unchanged": True, "sandbox_executed": False}
    report["user_scenarios"] = user_scenarios
    output = Path(__file__).resolve().parents[1] / "output/platform-integration/verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: real HTTP knowledge + embedding + Skill ZIP chain; report:", output, flush=True)


if __name__ == "__main__":
    main()
