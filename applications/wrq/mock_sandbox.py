"""本地联调专用的同事沙箱 Mock。

只有 WRQ_SANDBOX_MOCK=true 时才会被 main.py 挂载；正式环境默认不启用。
返回合同与真实 /realtime-test-case-gen 一致，包括多 documents 下载。
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from tortoise import connections

from applications.wrq.auth import DependAuth, user_login_name

router = APIRouter(prefix="/realtime-test-case-gen", tags=["local-sandbox-mock"])
_runs: dict[str, dict] = {}
_polls: dict[str, int] = {}
_latest: dict[str, str] = {}
TZ = timezone(timedelta(hours=8))

PRESETS = {
    "e2e-20261028-passed": ("e2e1028passed", [
        ("登录正向用例.xlsx", 8), ("登录异常用例.xlsx", 6), ("登录边界用例.xlsx", 4),
    ]),
    "e2e-20261028-online": ("e2e1028online", [
        ("核心功能回归.xlsx", 12), ("权限功能回归.xlsx", 9),
    ]),
    "e2e-20261028-offline": ("e2e1028offline", [
        ("下线前基线.xlsx", 10), ("兼容性用例.xlsx", 7), ("性能用例.xlsx", 5), ("安全用例.xlsx", 6),
    ]),
}


def _now():
    return datetime.now(TZ)


def _documents(run_id: str, values: list[tuple[str, int]]):
    expiry = (_now() + timedelta(days=1)).isoformat()
    return [{
        "filename": filename,
        "format": "xlsx",
        "size_bytes": 8192 + count * 431,
        "test_case_count": count,
        "download_url": f"/realtime-test-case-gen/runs/{run_id}/document?filename={quote(filename)}",
        "expires_at": expiry,
    } for filename, count in values]


def _preset(skill_id: str, run_id: str, values: list[tuple[str, int]]):
    started = _now() - timedelta(minutes=2)
    return {"run_id": run_id, "skill_id": skill_id, "debugger": "系统管理员", "status": "completed",
        "started_at": started.isoformat(), "finished_at": (started + timedelta(seconds=75)).isoformat(),
        "error_message": None, "documents": _documents(run_id, values)}


for _skill_id, (_run_id, _values) in PRESETS.items():
    _runs[_run_id] = _preset(_skill_id, _run_id, _values)
    _latest[_skill_id] = _run_id


async def _upsert_peer_row(row: dict):
    started = datetime.fromisoformat(row["started_at"]) if row.get("started_at") else None
    finished = datetime.fromisoformat(row["finished_at"]) if row.get("finished_at") else None
    expires = _now() + timedelta(days=1) if row["status"] == "completed" else None
    await connections.get("default").execute_query(
        "INSERT INTO keenrobot_online_debug_runs (skill_id,run_id,status,error_message,started_at,finished_at,expires_at,debugger) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE status=VALUES(status),error_message=VALUES(error_message),"
        "started_at=VALUES(started_at),finished_at=VALUES(finished_at),expires_at=VALUES(expires_at),debugger=VALUES(debugger)",
        [row["skill_id"], row["run_id"], row["status"], row.get("error_message"), started, finished, expires, row["debugger"]],
    )


@router.post("/runs")
async def create_run(skill_id: str = Form(...), mock_outcome: str = Form("success"), current_user=DependAuth):
    run_id = uuid.uuid4().hex
    row = {"run_id": run_id, "skill_id": skill_id, "debugger": current_user.alias or user_login_name(current_user),
        "status": "queued", "started_at": None, "finished_at": None, "error_message": None, "documents": []}
    # 仅本地 Mock 的失败演练开关；真实前端合同不传该字段，因此默认仍走成功流程。
    if mock_outcome.strip().lower() in {"failed", "failure", "error"}:
        now = _now().isoformat()
        row.update(status="failed", started_at=now, finished_at=now,
                   error_message="模拟失败：沙箱执行过程中发生测试错误")
    _runs[run_id] = row
    _polls[run_id] = 0
    _latest[skill_id] = run_id
    await _upsert_peer_row(row)
    return row


@router.get("/runs/{run_id}")
async def get_run(run_id: str, current_user=DependAuth):
    row = _runs.get(run_id)
    if not row:
        raise HTTPException(404, "Mock 任务不存在")
    if row["status"] in ("queued", "running"):
        count = _polls.get(run_id, 0) + 1
        _polls[run_id] = count
        if count == 1:
            row.update(status="running", started_at=_now().isoformat())
        else:
            row.update(status="completed", finished_at=_now().isoformat(), documents=_documents(run_id, [
                ("主流程测试用例.xlsx", 10), ("异常流程测试用例.xlsx", 7), ("边界值测试用例.xlsx", 5),
            ]))
        await _upsert_peer_row(row)
    return row


@router.get("/skills/{skill_id}/latest-run")
async def latest_run(skill_id: str, current_user=DependAuth):
    run_id = _latest.get(skill_id)
    if not run_id:
        raise HTTPException(404, "Mock 中尚无该技能任务")
    return _runs[run_id]


def _excel(filename: str, count: int):
    book = Workbook()
    sheet = book.active
    sheet.title = "测试用例"
    sheet.append(["编号", "所属文件", "测试场景", "预期结果"])
    for index in range(1, count + 1):
        sheet.append([f"TC-{index:03d}", filename, f"{filename.removesuffix('.xlsx')}场景 {index}", "系统按规则处理"])
    stream = BytesIO()
    book.save(stream)
    book.close()
    stream.seek(0)
    return stream


@router.get("/runs/{run_id}/document")
async def download_document(run_id: str, filename: str = Query(...), current_user=DependAuth):
    row = _runs.get(run_id)
    if not row:
        raise HTTPException(404, "Mock 任务不存在")
    if row["status"] != "completed":
        raise HTTPException(409, "Mock 任务尚未完成")
    document = next((item for item in row["documents"] if item["filename"] == filename), None)
    if not document:
        raise HTTPException(404, "Mock 结果文档不存在")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(_excel(filename, document["test_case_count"]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)
