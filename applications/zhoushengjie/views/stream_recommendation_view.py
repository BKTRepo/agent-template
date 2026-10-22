# -*- coding: utf-8 -*-
"""
@Author  : zhoushengjie
@Project : KeenRobot
@Module  : stream_recommendation_view.py
@DateTime: 2026/6/15

用例推荐流式接口。
提供两个 SSE 接口：
1. /streamRecommendation — 流式生成推荐用例（完整过程：文本 + 思考 + 工具调用）
2. /streamRecommendationThinking — 仅流式推送思考过程

两者共用 stream_recommend_generate 生成器，区别在于 SSE 事件过滤策略。
"""
import json
import os
import shutil
import tarfile

import aiofiles
from fastapi import APIRouter, File, Form, UploadFile
from sse_starlette.sse import EventSourceResponse

from applications.zhoushengjie.services.stream_recommend_generator import (
    stream_recommend_generate,
)
from services.claude_stream_service import THINKING_EVENT_WHITELIST
from common.file_converter import convert_file_to_md
from configure import LOGGER, PROJECT_CONFIG
from core.responses import FailureResponse

stream_recommendation_router = APIRouter()

_WORKSPACE_DIR = PROJECT_CONFIG.WORKSPACE_DIR
_CHUNK_SIZE = 1024 * 1024 * 10


async def _save_upload_file(upload_file: UploadFile, dest_path: str):
    """异步分块保存上传文件。"""
    async with aiofiles.open(dest_path, "wb") as f:
        while True:
            chunk = await upload_file.read(_CHUNK_SIZE)
            if not chunk:
                break
            await f.write(chunk)
        await upload_file.close()


def _process_files(base_dir: str, file_mapping: dict):
    """预处理文件：xlsx→md、tar 解压。"""
    # xlsx → md
    for name in ["atpmCases", "caseExcel"]:
        xlsx_filename = file_mapping.get(name, "")
        if not xlsx_filename:
            continue
        xlsx_path = os.path.join(base_dir, xlsx_filename)
        if not os.path.isfile(xlsx_path):
            continue
        try:
            md_path = convert_file_to_md(xlsx_path)
            LOGGER.info(f"【Stream】转换 {name} 完成: {xlsx_path} -> {md_path}")
            os.remove(xlsx_path)
        except Exception as e:
            LOGGER.exception(f"【Stream】转换 {name} 失败: {e}")

    # tar 解压
    tar_filename = file_mapping.get("fullPackage", "")
    if tar_filename:
        tar_path = os.path.join(base_dir, tar_filename)
        extract_dir = os.path.join(base_dir, "code_coverage_file")
        if os.path.isfile(tar_path) and tarfile.is_tarfile(tar_path):
            os.makedirs(extract_dir, exist_ok=True)
            with tarfile.open(tar_path, "r") as tar:
                tar.extractall(path=extract_dir)

            report_dir = os.path.join(extract_dir, "report")
            increment_dir = os.path.join(report_dir, "increment")
            full_dir = os.path.join(report_dir, "full")

            if os.path.isdir(increment_dir):
                shutil.rmtree(increment_dir)

            if os.path.isdir(full_dir):
                for item in os.listdir(full_dir):
                    src = os.path.join(full_dir, item)
                    dst = os.path.join(extract_dir, item)
                    if os.path.exists(dst):
                        if os.path.isdir(dst):
                            shutil.rmtree(dst)
                        else:
                            os.remove(dst)
                    shutil.move(src, dst)
                shutil.rmtree(full_dir)

            if os.path.isdir(report_dir) and not os.listdir(report_dir):
                shutil.rmtree(report_dir)




@stream_recommendation_router.post("/streamRecommendation", summary="流式生成推荐用例（完整过程）")
async def stream_recommendation(
    atpmCases: UploadFile = File(...),
    caseExcel: UploadFile = File(...),
    projectAiCodeTestScriptId: str = Form(...),
    diffJson: UploadFile = File(...),
    fullPackage: UploadFile = File(...),
    model: str = Form("sonnet"),
):
    """SSE 流式接口：推送完整过程，包括：
    - meta: 元数据（project_id, model）
    - text: 文本增量
    - thinking_start / thinking: 思考过程
    - tool_start / tool_input / tool_done: 工具调用状态
    - done: 最终完成
    - error: 错误
    """
    try:
        base_dir = os.path.join(_WORKSPACE_DIR, "case_recommendation", projectAiCodeTestScriptId)
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir)
        os.makedirs(base_dir, exist_ok=True)

        file_mapping = {
            "atpmCases": "atpm_case.xlsx",
            "caseExcel": "user_case.xlsx",
            "diffJson": "diffCodeFiles.json",
            "fullPackage": fullPackage.filename,
        }

        upload_files = {
            "atpmCases": atpmCases,
            "caseExcel": caseExcel,
            "diffJson": diffJson,
            "fullPackage": fullPackage,
        }

        for name, upload_file in upload_files.items():
            dest_path = os.path.join(base_dir, file_mapping[name])
            await _save_upload_file(upload_file, dest_path)

        # 预处理文件（xlsx→md、tar解压）
        _process_files(base_dir, file_mapping)
        LOGGER.info(f"【Stream】文件预处理完成: project_id={projectAiCodeTestScriptId}")

        async def event_generator():
            # 元数据事件
            yield {
                "event": "meta",
                "data": json.dumps({
                    "type": "meta",
                    "project_id": projectAiCodeTestScriptId,
                    "model": model,
                }, ensure_ascii=False),
            }

            # 流式调用 Agent SDK
            async for event_dict in stream_recommend_generate(
                project_id=projectAiCodeTestScriptId,
                model=model,
            ):
                yield {
                    "event": event_dict["event"],
                    "data": json.dumps(event_dict["data"], ensure_ascii=False),
                }

        return EventSourceResponse(event_generator())

    except Exception as e:
        LOGGER.exception(f"【Stream】流式推荐生成失败: {e}")
        return FailureResponse(message=f"流式推荐生成失败：{str(e)}")


@stream_recommendation_router.post("/streamRecommendationThinking", summary="流式生成推荐用例（仅思考过程）")
async def stream_recommendation_thinking(
    atpmCases: UploadFile = File(...),
    caseExcel: UploadFile = File(...),
    projectAiCodeTestScriptId: str = Form(...),
    diffJson: UploadFile = File(...),
    fullPackage: UploadFile = File(...),
    model: str = Form("sonnet"),
):
    """SSE 流式接口：仅推送思考过程 + 最终结果 + 错误。

    与 /streamRecommendation 不同，此接口过滤掉工具调用细节和文本增量，
    只保留思考过程（thinking）、最终完成（done）和错误（error）。

    SSE 事件类型：
    - meta: 元数据
    - thinking_start / thinking: 思考过程增量
    - thinking_done: 思考阶段结束（在工具开始时触发）
    - done: 最终完成
    - error: 错误
    """
    try:
        base_dir = os.path.join(_WORKSPACE_DIR, "case_recommendation", projectAiCodeTestScriptId)
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir)
        os.makedirs(base_dir, exist_ok=True)

        file_mapping = {
            "atpmCases": "atpm_case.xlsx",
            "caseExcel": "user_case.xlsx",
            "diffJson": "diffCodeFiles.json",
            "fullPackage": fullPackage.filename,
        }

        upload_files = {
            "atpmCases": atpmCases,
            "caseExcel": caseExcel,
            "diffJson": diffJson,
            "fullPackage": fullPackage,
        }

        for name, upload_file in upload_files.items():
            dest_path = os.path.join(base_dir, file_mapping[name])
            await _save_upload_file(upload_file, dest_path)

        # 预处理文件
        _process_files(base_dir, file_mapping)

        async def event_generator():
            yield {
                "event": "meta",
                "data": json.dumps({
                    "type": "meta",
                    "project_id": projectAiCodeTestScriptId,
                    "model": model,
                }, ensure_ascii=False),
            }

            thinking_ended = False

            async for event_dict in stream_recommend_generate(
                project_id=projectAiCodeTestScriptId,
                model=model,
            ):
                event_type = event_dict["event"]

                # 只推送 thinking/done/error
                if event_type in THINKING_EVENT_WHITELIST:
                    yield {
                        "event": event_type,
                        "data": json.dumps(event_dict["data"], ensure_ascii=False),
                    }
                elif event_type == "tool_start" and not thinking_ended:
                    # 工具开始意味着思考阶段结束
                    thinking_ended = True
                    yield {
                        "event": "thinking_done",
                        "data": json.dumps({"type": "thinking_done"}, ensure_ascii=False),
                    }

        return EventSourceResponse(event_generator())

    except Exception as e:
        LOGGER.exception(f"【Stream】流式推荐思考过程失败: {e}")
        return FailureResponse(message=f"流式推荐思考过程失败：{str(e)}")
