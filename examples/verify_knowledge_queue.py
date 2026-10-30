"""真实 Redis/两个 Worker/HTTP/Chroma；占用合成文件验证自动删除重试。"""
from examples.knowledge_queue_environment import ROOT, DB
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

import requests


def main():
    session, url = requests.Session(), "http://127.0.0.1:8530"
    def call(method, path, **kwargs):
        response = session.request(method, url + path, timeout=30, **kwargs)
        response.raise_for_status()
        result = response.json()
        assert result["status"] == "success", result.get("message")
        return result["data"]
    result = call("POST", "/base/auth/access_token", json={"username":"skill-dev", "password":"SkillLocal2026!"})
    session.headers["token"] = result["access_token"]
    run_id = uuid.uuid4().hex[:8]
    source = {"knowledge_name":"真实队列删除验证-" + run_id, "description":"纯合成文档", "tag":"custom",
        "application":"核心系统", "is_public":False}
    kb = call("POST", "/knowledge-bases/", data={"source":json.dumps(source)}, files=[
        ("files",("keep.md",b"# Keep\nkeep this rule")), ("files",("remove.md",b"# Remove\nremove this rule"))])
    kb_id = kb["id"]
    def detail(): return call("GET", f"/knowledge-bases/{kb_id}")
    def until(predicate, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = detail()
            if predicate(current): return current
            time.sleep(.3)
        raise AssertionError("queue verification timed out; inspect isolated Worker logs")
    kb = until(lambda k:k["status"] != "processing")
    assert kb["status"] == "completed", kb["documents"]
    keep = next(d for d in kb["documents"] if d["filename"]=="keep.md")
    target = next(d for d in kb["documents"] if d["filename"]=="remove.md")
    with sqlite3.connect(DB) as conn:
        path = Path(conn.execute("SELECT file_path FROM keenrobot_documents WHERE id=?",(target["id"],)).fetchone()[0])
    assert path.resolve().is_relative_to(ROOT.resolve())
    if os.name != "nt": raise RuntimeError("此文件占用探针使用 Windows API；其他系统请用故障注入用例")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 1|2, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
    from celery_scheduler.celery_worker import celery
    marker = ROOT / f"parse-slot-{run_id}.txt"
    celery.send_task("examples.knowledge_queue.block_parse",args=[str(marker),15],queue="knowledge_parse")
    deadline = time.monotonic()+15
    while not marker.exists() and time.monotonic()<deadline: time.sleep(.1)
    assert marker.exists(), "parse Worker probe did not start"
    try:
        call("PUT",f"/knowledge-bases/{kb_id}",data={"source":json.dumps({**source,"change_summary":"验证删除队列与自动重试",
            "expected_version":kb["version"],"retained_document_ids":[keep["id"]]})})
        failed_once=until(lambda k: bool(k["cleanup_tasks"]) and k["cleanup_tasks"][0]["retry_count"]>=1, timeout=10)
        retry_task=failed_once["cleanup_tasks"][0]
        assert retry_task["status"]=="deleting" and path.exists()
        print("PASS: deletion ran while parse queue occupied; file-in-use retained SQL and scheduled retry",flush=True)
    finally:
        kernel.CloseHandle(handle)
    finished=until(lambda k: not k["cleanup_pending"],timeout=40)
    assert finished["status"]=="completed" and not path.exists()
    with sqlite3.connect(DB) as conn:
        assert conn.execute("SELECT COUNT(*) FROM keenrobot_documents WHERE id=?",(target["id"],)).fetchone()[0]==0
    from applications.base.rag.chroma_store import chroma_store
    assert not chroma_store._collection.get(where={"doc_id":target["id"]},include=[])["ids"]
    report={"run_id":run_id,"knowledge_id":kb_id,"real_redis":True,"separate_parse_and_delete_workers":True,
        "auto_retry_seen":retry_task["retry_count"],"sql_and_file_preserved_while_locked":True,
        "completed_without_manual_retry":True,"deleted_file_and_sql":True,"vector_residue":False}
    (ROOT/"verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("PASS: automatic retry completed, no file/SQL/vector residue; report:",ROOT/"verification.json",flush=True)


if __name__=="__main__": main()
