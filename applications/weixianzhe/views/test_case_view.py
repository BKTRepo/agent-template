# -*- coding: utf-8 -*-
"""
@Author  : weixianzhe & zhoushengjie
@Project : KeenRobot
@Module  : test_case_view.py
@DateTime: 2026/6/15

测试用例生成视图层。
接口收到请求后立即返回 task_id，后续生成逻辑由 Celery Worker 异步执行。
"""
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse

from applications.weixianzhe.models.test_case_task_model import TestCaseTask
from applications.weixianzhe.schemas.test_case_schema import TaskInfo, TaskListResponse
from applications.weixianzhe.utils.xlsx_writer import md_to_xlsx
from configure import LOGGER, PROJECT_CONFIG
from core.responses import FailureResponse, SuccessResponse

test_case_router = APIRouter()


@test_case_router.get("/health", summary="健康检查")
def health():
    return SuccessResponse(data={"status": "ok"})


@test_case_router.post("/generateTestCases", summary="生成测试用例")
async def generate_test_cases(
    request: Request,
    files: list[UploadFile] = File(...),
    app_system: str = Form(""),
    requirement_name: str = Form(""),
):
    """接收请求 → 保存文件 + 创建任务记录 → 投递 Celery → 立即返回 task_id"""
    if not files:
        return FailureResponse(message="请至少上传一个文件")

    # 1) 校验文件
    files_data = []
    for file in files:
        if not file.filename or not file.filename.lower().endswith(".docx"):
            return FailureResponse(message=f"文件「{file.filename}」不是 .docx 格式")
        docx_bytes = await file.read()
        if not docx_bytes:
            return FailureResponse(message=f"文件「{file.filename}」为空")
        safe_filename = os.path.basename(file.filename)
        files_data.append((docx_bytes, safe_filename))

    creater_user = request.headers.get("x-real-ip") or "user"

    # 2) 创建任务文件夹
    base_dir = os.path.join(PROJECT_CONFIG.WORKSPACE_DIR, "test_case")
    folder_path = os.path.abspath(os.path.join(base_dir, uuid.uuid4().hex))
    os.makedirs(folder_path, exist_ok=True)

    # 3) 保存源文件到文件夹
    saved_filenames: list[str] = []
    for docx_bytes, filename in files_data:
        source_path = os.path.join(folder_path, filename)
        with open(source_path, "wb") as f:
            f.write(docx_bytes)
        saved_filenames.append(filename)

    # 4) 创建数据库任务记录（状态 = pending）
    record = await TestCaseTask.create(
        folder_path=folder_path,
        app_system=app_system,
        requirement_name=requirement_name,
        status="pending",
        created_user=creater_user,
        updated_user=creater_user,
    )

    # 5) 投递 Celery 任务
    from celery_scheduler.celery_worker import celery
    celery.send_task(
        "celery_scheduler.tasks.task_test_case_gen.generate_test_cases_task",
        kwargs={
            "task_id": record.id,
            "folder_path": folder_path,
            "source_filenames": saved_filenames,
        },
    )

    return SuccessResponse(data={"status": "accepted", "task_id": record.id})


@test_case_router.get("/tasks", summary="任务列表")
async def list_tasks(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(5, ge=1, le=100, description="每页条数"),
):
    offset = (page - 1) * limit

    try:
        total = await TestCaseTask.all().count()
        tasks = await TestCaseTask.all().order_by("-created_time").offset(offset).limit(limit)
    except Exception as exc:
        LOGGER.exception("查询任务列表失败: %s", exc)
        return FailureResponse(message=f"查询任务列表失败: {exc}")

    data = TaskListResponse(
        total=total,
        page=page,
        limit=limit,
        items=[TaskInfo.model_validate(task) for task in tasks],
    )
    return SuccessResponse(data=data.model_dump(by_alias=True))


@test_case_router.get("/testCasesContent", summary="获取测试用例内容")
async def get_test_cases_content(task_id: int = Query(..., alias="taskId")):
    """根据 task_id 读取 02-功能测试用例.md 内容，返回 markdown 字符串。"""
    try:
        task = await TestCaseTask.get_or_none(id=task_id)
    except Exception as exc:
        LOGGER.exception("查询任务失败: %s", exc)
        return FailureResponse(message=f"查询任务失败: {exc}")

    if not task:
        return FailureResponse(message="任务不存在")

    if task.status != "success":
        return FailureResponse(
            message=f"任务状态为「{task.status}」，无法获取测试用例内容",
        )

    folder_path = task.folder_path
    if not folder_path:
        return FailureResponse(message="任务输出路径为空")

    md_path = Path(folder_path) / "02-功能测试用例.md"
    if not md_path.exists():
        return FailureResponse(message="未找到功能测试用例文件")

    content = md_path.read_text(encoding="utf-8")
    return SuccessResponse(data={"content": content})


@test_case_router.get("/downloadMarkdown", summary="下载测试用例 Markdown")
async def download_test_cases_markdown(task_id: int = Query(..., alias="taskId")):
    """根据 task_id 下载 02-功能测试用例.md"""
    try:
        task = await TestCaseTask.get_or_none(id=task_id)
    except Exception as exc:
        LOGGER.exception("查询任务失败: %s", exc)
        return FailureResponse(message=f"查询任务失败: {exc}")

    if not task:
        return FailureResponse(message="任务不存在")

    if task.status != "success":
        return FailureResponse(
            message=f"任务状态为「{task.status}」，无法下载测试用例",
        )

    folder_path = task.folder_path
    if not folder_path:
        return FailureResponse(message="任务输出路径为空")

    md_path = Path(folder_path) / "02-功能测试用例.md"
    if not md_path.exists():
        return FailureResponse(message="未找到功能测试用例文件")

    filename = f"{task.requirement_name}_功能测试用例.md" if task.requirement_name else "02-功能测试用例.md"

    return FileResponse(
        path=str(md_path),
        filename=filename,
        media_type="text/markdown; charset=utf-8",
    )


@test_case_router.get("/downloadXlsx", summary="下载测试用例 XLSX")
async def download_test_cases_xlsx(
    background_tasks: BackgroundTasks,
    task_id: int = Query(..., alias="taskId"),
):
    """根据 task_id 查询对应输出目录下的 02-功能测试用例.md，转换为 XLSX 后返回下载。"""
    try:
        task = await TestCaseTask.get_or_none(id=task_id)
    except Exception as exc:
        LOGGER.exception("查询任务失败: %s", exc)
        return FailureResponse(message=f"查询任务失败: {exc}")

    if not task:
        return FailureResponse(message="任务不存在")

    if task.status != "success":
        return FailureResponse(
            message=f"任务状态为「{task.status}」，无法下载测试用例",
        )

    folder_path = task.folder_path
    if not folder_path:
        return FailureResponse(message="任务输出路径为空")

    md_path = Path(folder_path) / "02-功能测试用例.md"
    if not md_path.exists():
        return FailureResponse(message="未找到功能测试用例文件")

    xlsx_path = md_path.with_suffix(".xlsx.tmp")
    try:
        md_to_xlsx(str(md_path), str(xlsx_path))
    except Exception as exc:
        LOGGER.exception("XLSX 转换失败: %s", exc)
        xlsx_path.unlink(missing_ok=True)
        return FailureResponse(message="xlsx文件转换失败，请下载原始markdown文件")

    background_tasks.add_task(xlsx_path.unlink)

    filename = f"{task.requirement_name}_功能测试用例.xlsx" if task.requirement_name else "测试用例.xlsx"

    return FileResponse(
        path=str(xlsx_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
