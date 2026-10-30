"""开发者中心在线调试接口：创建任务、查询状态和下载 Skill 生成的结果文件。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from applications.user.models.user_model import User
from applications.zhaoyunlong.schemas.online_debug_schema import OnlineModelDebugRequest
from applications.zhaoyunlong.services.online_debug_file_parser import (
    FileParseError,
    extract_mounted_resource,
    extract_uploaded_file,
)
from applications.zhaoyunlong.services.online_debug_run_service import (
    OnlineDebugRunNotFoundError,
    OnlineDebugRunService,
)
from applications.zhaoyunlong.services.online_debug_service import OnlineDebugError
from services import DependAuth

realtime_test_case_router = APIRouter()


@realtime_test_case_router.post(
    "/runs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="创建在线调试任务",
    description="接收 Skill 定义、对话输入和上传文件，创建后台 Docker 沙箱任务并立即返回 run_id。",
    openapi_extra={"requestBody": {"required": True, "content": {
        "multipart/form-data": {"schema": {"type": "object", "required": ["skill_id", "skill_definition"], "properties": {
            "skill_id": {"type": "string", "description": "当前被调试技能的业务标识"},
            "skill_definition": {"type": "string", "description": "Markdown 格式的 Skill 定义文本"},
            "conversation_input": {"type": "string", "description": "自然语言调试诉求"},
            "documents": {"type": "array", "description": "需求文档文件，最多 10 个", "items": {"type": "string", "format": "binary"}},
            "mounted_resources": {"type": "array", "description": "已挂载的只读资源，最多 20 个；不重复进行前端上传格式白名单校验", "items": {"type": "string", "format": "binary"}},
        }}},
    }}},
)
async def create_online_debug_run(
    request: Request,
    current_user: User = DependAuth,
) -> dict[str, Any]:
    """【创建调试任务接口】立即返回任务编号，沙箱在后台继续执行。"""
    try:
        payload = await _parse_debug_request(request)
        debugger = (current_user.alias or current_user.username).strip()
        return await OnlineDebugRunService.create_and_start(payload, int(current_user.id), debugger)
    except (OnlineDebugError, FileParseError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@realtime_test_case_router.get(
    "/runs/{run_id}",
    summary="查询在线调试任务状态",
    description="根据 run_id 查询任务的 queued、running、completed 或 failed 状态及结果文档信息。",
)
async def get_online_debug_run(
    run_id: str,
    current_user: User = DependAuth,
) -> dict[str, Any]:
    """【查询调试任务接口】供前端每隔一段时间轮询当前任务状态。"""
    try:
        record = await OnlineDebugRunService.get_run(
            run_id,
        )
        return await OnlineDebugRunService.as_response(record)
    except OnlineDebugRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@realtime_test_case_router.get(
    "/skills/{skill_id}/latest-run",
    summary="查询技能最近一次在线调试任务",
    description="弹窗重新打开时，根据 skill_id 找回该技能最近一次调试的状态和结果。",
)
async def get_latest_online_debug_run(
    skill_id: str,
    current_user: User = DependAuth,
) -> dict[str, Any]:
    """【查询技能最新任务接口】用于恢复已关闭调试弹窗的展示状态。"""
    try:
        record = await OnlineDebugRunService.get_latest_run(
            skill_id,
        )
        return await OnlineDebugRunService.as_response(record)
    except OnlineDebugRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@realtime_test_case_router.get(
    "/runs/{run_id}/document",
    summary="下载在线调试结果文件",
    description="仅当调试任务 completed 时下载结果文件；多个结果时传 filename 下载指定文件。",
)
async def download_online_debug_document(
    run_id: str,
    filename: str | None = Query(default=None, description="多个结果文件时指定要下载的文件名"),
    current_user: User = DependAuth,
) -> FileResponse:
    """【下载调试结果文件接口】单文件直接下载；多文件按 filename 下载指定文件。"""
    try:
        file_path, filename, media_type = await OnlineDebugRunService.get_document_path(
            run_id,
            int(current_user.id),
            bool(current_user.is_superuser),
            filename,
        )
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type=media_type,
        )
    except OnlineDebugRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OnlineDebugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
async def _parse_debug_request(request: Request) -> dict[str, Any]:
    """解析开发者中心传入的 multipart 在线调试表单。"""
    content_type = request.headers.get("content-type", "").lower()
    if not content_type.startswith("multipart/form-data"):
        raise ValueError("Content-Type 必须为 multipart/form-data")
    form = await request.form(max_files=30, max_fields=20)
    text_fields = OnlineModelDebugRequest.model_validate({
        "skill_id": _form_text(form.get("skill_id"), "skill_id", required=True),
        "skill_definition": _form_text(form.get("skill_definition"), "skill_definition", required=True),
        "conversation_input": _form_text(form.get("conversation_input"), "conversation_input"),
    }).model_dump()
    return {
        **text_fields,
        # 文档输入来自本次前端上传，必须执行允许格式校验。
        "documents": await _parse_uploads(
            form.getlist("documents"), "documents", 10, extract_uploaded_file,
        ),
        # 挂载资源已由资源系统管理，此处只读取文本，不重复进行格式白名单校验。
        "mounted_resources": await _parse_uploads(
            form.getlist("mounted_resources"), "mounted_resources", 20, extract_mounted_resource,
        ),
    }


def _form_text(value: object, name: str, *, required: bool = False) -> str:
    """读取 multipart 普通文本字段，禁止以文件代替。"""
    if value is None:
        if required:
            raise ValueError(f"缺少必填字段：{name}")
        return ""
    if isinstance(value, UploadFile):
        raise ValueError(f"{name} 必须是文本字段")
    text = str(value)
    if required and not text.strip():
        raise ValueError(f"缺少必填字段：{name}")
    return text


async def _parse_uploads(
    items: list[object],
    name: str,
    limit: int,
    parser: Any,
) -> list[dict[str, str]]:
    """读取文件并交给对应来源的解析器；文档与已挂载资源采用不同校验策略。"""
    if len(items) > limit:
        raise ValueError(f"{name} 最多上传 {limit} 个文件")
    result: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, UploadFile):
            raise ValueError(f"{name} 必须为文件字段")
        try:
            result.append(parser(item.filename or "", await item.read()))
        finally:
            await item.close()
    return result
