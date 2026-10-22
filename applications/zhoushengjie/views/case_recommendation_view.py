# -*- coding: utf-8 -*-
"""
@Author  : zhoushengjie
@Project : KeenRobot
@Module  : case_recommendation_view.py
@DateTime: 2026/6/15

用例推荐视图层。
接口收到请求后：保存文件 → 投递 Celery → 立即返回。
所有处理逻辑（xlsx→csv、tar 解压、Claude SDK 调用）由 Celery Worker 后台执行。
"""
import csv
import os
import shutil
from typing import List

import aiofiles
from fastapi import APIRouter, File, Form, UploadFile

from configure import LOGGER, PROJECT_CONFIG
from core.responses import FailureResponse, SuccessResponse

case_recommendation_router = APIRouter()

_WORKSPACE_DIR = PROJECT_CONFIG.WORKSPACE_DIR


async def _save_upload_file(upload_file: UploadFile, dest_path: str, chunk_size: int):
    """异步分块保存上传文件。"""
    async with aiofiles.open(dest_path, "wb") as f:
        while True:
            chunk = await upload_file.read(chunk_size)
            if not chunk:
                break
            await f.write(chunk)
        await upload_file.close()


def _read_csv_to_list(csv_path: str, case_type: str, project_id: str) -> List[dict]:
    """读取 CSV 文件并转为结构化列表。"""
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            item = {
                "projectAiCodeTestScriptId": project_id,
                "testCaseNumber": row.get("testCaseNumber", ""),
                "testCaseName": row.get("testCaseName", ""),
                "applicationModel": row.get("applicationModel", ""),
                "priority": row.get("priority", ""),
                "testCaseType": row.get("testCaseType", ""),
                "feedbackStatus": row.get("feedbackStatus", ""),
                "type": case_type,
            }
            rows.append(item)
    return rows


@case_recommendation_router.post("/uploadCaseFiles", summary="上传用例推荐文件")
async def upload_case_files(
    atpmCases: UploadFile = File(...),
    caseExcel: UploadFile = File(...),
    projectAiCodeTestScriptId: str = Form(...),
    diffJson: UploadFile = File(...),
    fullPackage: UploadFile = File(...),
):
    """接收文件 → 保存 → 投递 Celery → 立即返回"""
    chunk_size = 1024 * 1024 * 10
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
            await _save_upload_file(upload_file, dest_path, chunk_size)

        # 投递 Celery 任务（文件处理 + Claude SDK 调用全部在 Worker 中执行）
        from celery_scheduler.celery_worker import celery
        celery.send_task(
            "celery_scheduler.tasks.task_case_recommendation.run_case_recommendation_task",
            kwargs={
                "project_id": projectAiCodeTestScriptId,
                "file_mapping": file_mapping,
            },
        )
        LOGGER.info(f"【View】已投递 Celery 用例推荐任务: project_id={projectAiCodeTestScriptId}")

        return SuccessResponse(data={"projectAiCodeTestScriptId": projectAiCodeTestScriptId})
    except Exception as e:
        LOGGER.exception(str(e))
        return FailureResponse(message=f"上传失败：{str(e)}")


@case_recommendation_router.post("/getCaseRecommendationResult", summary="获取用例推荐结果")
async def get_case_recommendation_result(projectAiCodeTestScriptId: str = Form(...)):
    """查询推荐结果：检查 error.txt（失败）或读取 csv（成功）或返回空（进行中）。"""
    base_dir = os.path.join(_WORKSPACE_DIR, "case_recommendation", projectAiCodeTestScriptId)

    if not os.path.exists(base_dir):
        return FailureResponse(message="projectAiCodeTestScriptId不存在")

    error_file = os.path.join(base_dir, "error.txt")
    if os.path.exists(error_file):
        with open(error_file, "r", encoding="utf-8") as f:
            error_msg = f.read()
        return FailureResponse(message=error_msg or "处理过程中发生错误")

    ai_cases_path = os.path.join(base_dir, "ai_cases.csv")
    recommended_cases_path = os.path.join(base_dir, "recommended_cases.csv")

    result = []

    if os.path.exists(recommended_cases_path):
        result.extend(_read_csv_to_list(recommended_cases_path, "1", projectAiCodeTestScriptId))
    if os.path.exists(ai_cases_path):
        result.extend(_read_csv_to_list(ai_cases_path, "2", projectAiCodeTestScriptId))

    if not result:
        return SuccessResponse(data=[], message="正在生成中，请稍后")

    return SuccessResponse(data=result)
