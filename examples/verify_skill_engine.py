"""仅验证 Skill 引擎：本机真实 HTTP，无知识库、无模型、无运行器依赖。"""
import argparse
import base64
import io
import json
from pathlib import Path
import uuid
import zipfile

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8520")
    args = parser.parse_args()
    if not args.url.startswith("http://127.0.0.1:"):
        parser.error("只允许向本机演示服务写入合成测试数据")
    session = requests.Session()
    base = args.url.rstrip("/")
    def call(method, path, **kwargs):
        response = session.request(method, base + path, timeout=45, **kwargs)
        response.raise_for_status()
        data = response.json()
        assert data["status"] == "success", data.get("message")
        return data["data"]
    login = call("POST", "/base/auth/access_token", json={"username": "skill-dev", "password": "SkillLocal2026!"})
    session.headers["token"] = login["access_token"]
    run_id = uuid.uuid4().hex[:8]
    skill = call("POST", "/skills/", json={"name": "Skill引擎测试-" + run_id, "is_enabled": False})
    source = {"skill_id": skill["id"], "skill_name": skill["name"], "skill_class_id": "SKILL-CASE-001",
        "description": "按转账需求生成正向、异常和边界测试用例。", "instructions": "先核对需求，缺少规则时列出问题，再生成测试用例。",
        "knowledge_base_ids": [], "resource_categories": []}
    def build(data, files=None):
        return call("POST", "/skills/form/builds", data={"source": json.dumps(data)}, files=files or [])
    def archive(built):
        response = session.get(base + f"/skills/{skill['id']}/builds/{built['build_id']}/download", timeout=45)
        response.raise_for_status()
        assert "application/zip" in response.headers.get("content-type", "")
        return zipfile.ZipFile(io.BytesIO(response.content))
    checks = []
    first = build(source)
    with archive(first) as package:
        assert package.namelist() == [f"{first['name']}/SKILL.md"]
    checks.append("无附件生成与下载")
    print("PASS: text-only Skill and ZIP", flush=True)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=")
    resources = [("files", ("rules.md", b"# Rules\nAmount must be positive.")),
                 ("files", ("flow.png", png)), ("files", ("check.py", b"raise RuntimeError('must not execute')\n"))]
    mixed = {**source, "resource_categories": ["reference", "asset", "script"],
        "resource_usage": "生成前查看规则和流程图，脚本供运行端使用。", "expected_version": first["version"]}
    second = build(mixed, resources)
    assert second["version"] == "1.0.1"
    with archive(second) as package:
        assert len(package.namelist()) == 4
        assert package.read(f"{second['name']}/assets/flow.png") == png
        assert package.read(f"{second['name']}/scripts/check.py") == resources[2][1][1]
    checks.append("文档图片脚本原样入包，版本递增，脚本未执行")
    print("PASS: resources, unchanged image/script, server version", flush=True)
    bad = session.post(base + "/skills/form/builds", data={"source": json.dumps({**mixed, "resource_usage": ""})},
                       files=resources, timeout=45)
    assert bad.json()["status"] == "failure"
    checks.append("有资源未填使用说明被拒绝")
    definition = call("GET", f"/skills/{skill['id']}/definition")
    assert definition["version"] == second["version"]
    edited = call("PUT", f"/skills/{skill['id']}/definition", json={"expected_version": second["version"],
        "markdown": definition["markdown"].replace("先核对需求", "先核对交易金额和需求")})
    assert edited["version"] == "1.0.2"
    checks.append("查询与Markdown保存重打包")
    stale = session.put(base + f"/skills/{skill['id']}/definition", json={"markdown": "过期修改", "expected_version": "1.0.0"}, timeout=45)
    assert stale.json()["status"] == "failure"
    with archive(first) as package:
        assert len(package.namelist()) == 1
    checks.append("过期编辑被拒绝，旧包仍可下载")
    report = {"run_id": run_id, "skill_id": skill["id"], "version": edited["version"],
        "build_id": edited["build_id"], "checks": checks, "knowledge_used": False, "agent_executed": False}
    path = Path(__file__).resolve().parents[1] / "output/skill-engine-verification.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: Skill engine HTTP checks; report:", path, flush=True)


if __name__ == "__main__": main()
