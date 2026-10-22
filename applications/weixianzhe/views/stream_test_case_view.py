# -*- coding: utf-8 -*-
"""
@Author  : weixianzhe & zhoushengjie
@Project : KeenRobot
@Module  : stream_test_case_view.py
@DateTime: 2026/6/15

测试用例生成流式接口。
提供两个 SSE 接口：
1. /streamGenerateTestCases — 流式生成测试用例（完整过程：文本 + 思考 + 工具调用）
2. /streamGenerateTestCasesThinking — 仅流式推送思考过程
"""
import json
import os
import uuid

from fastapi import APIRouter, File, Form, Request, UploadFile
from sse_starlette.sse import EventSourceResponse

from services.claude_stream_service import (
    build_stream_options,
    stream_agent_query,
    THINKING_EVENT_WHITELIST,
)
from common.file_converter import convert_file_to_md
from configure import LOGGER, PROJECT_CONFIG
from core.responses import FailureResponse

stream_test_case_router = APIRouter()


@stream_test_case_router.post("/streamGenerateTestCases", summary="流式生成测试用例（完整过程）")
async def stream_generate_test_cases(
    request: Request,
    files: list[UploadFile] = File(...),
    app_system: str = Form(""),
    requirement_name: str = Form(""),
    model: str = Form("sonnet"),
):
    """SSE 流式接口：推送完整过程，包括：
    - meta: 元数据
    - text: 文本增量
    - thinking_start / thinking: 思考过程
    - tool_start / tool_input / tool_done: 工具调用状态
    - done: 最终完成
    - error: 错误
    """
    if not files:
        return FailureResponse(message="请至少上传一个文件")

    # 1) 校验文件
    files_data = []
    for file in files:
        if not file.filename:
            return FailureResponse(message=f"文件「{file.filename}」无文件名")
        file_bytes = await file.read()
        if not file_bytes:
            return FailureResponse(message=f"文件「{file.filename}」为空")
        safe_filename = os.path.basename(file.filename)
        files_data.append((file_bytes, safe_filename))

    # 2) 创建任务文件夹
    base_dir = os.path.join(PROJECT_CONFIG.WORKSPACE_DIR, "test_case")
    folder_path = os.path.abspath(os.path.join(base_dir, uuid.uuid4().hex))
    os.makedirs(folder_path, exist_ok=True)

    # 3) 保存源文件 → 转换为 md
    for file_bytes, filename in files_data:
        source_path = os.path.join(folder_path, filename)
        with open(source_path, "wb") as f:
            f.write(file_bytes)
        # 如果是 docx/xlsx 等文档，转换为 md
        ext = os.path.splitext(filename)[1].lower()
        if ext in (".docx", ".xlsx", ".pptx", ".pdf"):
            try:
                md_path = convert_file_to_md(source_path)
                LOGGER.info(f"【Stream】转换 {filename} 完成: {source_path} -> {md_path}")
                os.remove(source_path)
            except Exception as e:
                LOGGER.exception(f"【Stream】转换 {filename} 失败: {e}")

    # 4) 流式调用
    prompt = (
        f"请读取 {folder_path} 目录中的所有 md 文档，按照 skill 的要求生成测试案例。"
        f"所有输出产物保存到 {folder_path} 目录。"
    )

    options = build_stream_options(
        skills=["test-case-generator"],
        output_dir=folder_path,
        model=model,
    )

    async def event_generator():
        yield {
            "event": "meta",
            "data": json.dumps({
                "type": "meta",
                "folder_path": folder_path,
                "model": model,
                "app_system": app_system,
                "requirement_name": requirement_name,
            }, ensure_ascii=False),
        }

        async for event_dict in stream_agent_query(prompt=prompt, options=options, log_tag="TestCase"):
            yield {
                "event": event_dict["event"],
                "data": json.dumps(event_dict["data"], ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


@stream_test_case_router.post("/streamGenerateTestCasesThinking", summary="流式生成测试用例（仅思考过程）")
async def stream_generate_test_cases_thinking(
    request: Request,
    files: list[UploadFile] = File(...),
    app_system: str = Form(""),
    requirement_name: str = Form(""),
    model: str = Form("sonnet"),
):
    """SSE 流式接口：仅推送思考过程 + 最终结果 + 错误。

    SSE 事件类型：
    - meta: 元数据
    - thinking_start / thinking: 思考过程增量
    - thinking_done: 思考阶段结束
    - done: 最终完成
    - error: 错误
    """
    if not files:
        return FailureResponse(message="请至少上传一个文件")

    # 1) 校验文件
    files_data = []
    for file in files:
        if not file.filename:
            return FailureResponse(message=f"文件「{file.filename}」无文件名")
        file_bytes = await file.read()
        if not file_bytes:
            return FailureResponse(message=f"文件「{file.filename}」为空")
        safe_filename = os.path.basename(file.filename)
        files_data.append((file_bytes, safe_filename))

    # 2) 创建任务文件夹
    base_dir = os.path.join(PROJECT_CONFIG.WORKSPACE_DIR, "test_case")
    folder_path = os.path.abspath(os.path.join(base_dir, uuid.uuid4().hex))
    os.makedirs(folder_path, exist_ok=True)

    # 3) 保存源文件 → 转换为 md
    for file_bytes, filename in files_data:
        source_path = os.path.join(folder_path, filename)
        with open(source_path, "wb") as f:
            f.write(file_bytes)
        ext = os.path.splitext(filename)[1].lower()
        if ext in (".docx", ".xlsx", ".pptx", ".pdf"):
            try:
                md_path = convert_file_to_md(source_path)
                LOGGER.info(f"【Stream】转换 {filename} 完成: {source_path} -> {md_path}")
                os.remove(source_path)
            except Exception as e:
                LOGGER.exception(f"【Stream】转换 {filename} 失败: {e}")

    # 4) 流式调用（仅思考）
    prompt = (
        f"请读取 {folder_path} 目录中的所有 md 文档，按照 skill 的要求生成测试案例。"
        f"所有输出产物保存到 {folder_path} 目录。"
    )

    options = build_stream_options(
        skills=["test-case-generator"],
        output_dir=folder_path,
        model=model,
    )

    async def event_generator():
        yield {
            "event": "meta",
            "data": json.dumps({
                "type": "meta",
                "folder_path": folder_path,
                "model": model,
            }, ensure_ascii=False),
        }

        thinking_ended = False

        async for event_dict in stream_agent_query(prompt=prompt, options=options, log_tag="TestCase"):
            event_type = event_dict["event"]

            if event_type in THINKING_EVENT_WHITELIST:
                yield {
                    "event": event_type,
                    "data": json.dumps(event_dict["data"], ensure_ascii=False),
                }
            elif event_type == "tool_start" and not thinking_ended:
                thinking_ended = True
                yield {
                    "event": "thinking_done",
                    "data": json.dumps({"type": "thinking_done"}, ensure_ascii=False),
                }

    return EventSourceResponse(event_generator())
