# -*- coding: utf-8 -*-
"""
@Author  : zhoushengjie
@Project : KeenRobot
@Module  : task_case_recommendation.py
@DateTime: 2026/6/15

Celery 异步任务：用例推荐生成。
所有处理逻辑（xlsx→md、tar 解压、Claude Agent SDK 调用）均在此任务中完成，
接口层仅负责保存上传文件 + 投递 Celery。
"""
import os
import shutil
import tarfile

from celery_scheduler.celery_base import init_tortoise_orm
from celery_scheduler.celery_worker import celery
from configure import LOGGER, PROJECT_CONFIG
from common.file_converter import convert_file_to_md


def _process_files(base_dir: str, file_mapping: dict):
    """步骤1: 文件处理（xlsx→md、tar 解压与目录整理）。"""
    # ---- xlsx → md ----
    xlsx_names = ["atpmCases", "caseExcel"]
    for name in xlsx_names:
        xlsx_filename = file_mapping.get(name, "")
        if not xlsx_filename:
            continue
        xlsx_path = os.path.join(base_dir, xlsx_filename)
        if not os.path.isfile(xlsx_path):
            continue
        try:
            md_path = convert_file_to_md(xlsx_path)
            LOGGER.info(f"【Celery】转换 {name} 完成: {xlsx_path} -> {md_path}")
            # 转换成功后删除原 xlsx
            os.remove(xlsx_path)
        except Exception as e:
            LOGGER.exception(f"【Celery】转换 {name} 失败: {str(e)}")

    # ---- tar 包解压 ----
    tar_path = os.path.join(base_dir, file_mapping.get("fullPackage", ""))
    extract_dir = os.path.join(base_dir, "code_coverage_file")
    if tar_path and os.path.exists(tar_path) and tarfile.is_tarfile(tar_path):
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


async def _run_case_recommendation_impl(
    project_id: str,
    file_mapping: dict,
) -> dict:
    """异步执行体：文件处理 → Claude Agent SDK 生成推荐测试用例。"""
    await init_tortoise_orm()

    from applications.zhoushengjie.services.claude_recommend_generator import (
        ClaudeTestCaseRecommendGenerator,
    )

    base_dir = os.path.join(PROJECT_CONFIG.WORKSPACE_DIR, "case_recommendation", project_id)

    # ---- 步骤1: 文件处理 ----
    _process_files(base_dir, file_mapping)
    LOGGER.info(f"【Celery】文件处理完成: project_id={project_id}")

    # ---- 步骤2: 调用 Claude Agent SDK 生成推荐测试用例（多模型轮询） ----
    generator = ClaudeTestCaseRecommendGenerator()
    result = await generator.generate(project_id)

    # ---- 步骤3: 校验产物 ----
    ai_cases_path = os.path.join(base_dir, "ai_cases.csv")
    recommended_cases_path = os.path.join(base_dir, "recommended_cases.csv")
    if not os.path.isfile(ai_cases_path) and not os.path.isfile(recommended_cases_path):
        LOGGER.warning(
            "Agent 执行完毕但未生成推荐产物, result_text 前200字符: %s",
            result[:200],
        )
        raise RuntimeError("Agent 执行完成但未生成 ai_cases.csv / recommended_cases.csv")

    LOGGER.info(f"【Celery】用例推荐任务完成: project_id={project_id}")
    return {"success": True, "result": result[:200]}


@celery.task(
    name="celery_scheduler.tasks.task_case_recommendation.run_case_recommendation_task",
    soft_time_limit=1800,
    time_limit=2000,
)
async def run_case_recommendation_task(
    project_id: str,
    file_mapping: dict,
) -> dict:
    """Celery 入口：根据 project_id 后台执行用例推荐生成（文件处理 + Claude 调用）。

    Args:
        project_id: 项目标识（对应 workspace/case_recommendation/{project_id} 目录）。
        file_mapping: 上传文件名映射，如 {"atpmCases": "atpm_case.xlsx", ...}。
    """
    try:
        return await _run_case_recommendation_impl(project_id, file_mapping)
    except Exception as exc:
        LOGGER.exception(f"【Celery】用例推荐任务失败: {exc}")
        # 写 error.txt 以便前端感知失败
        try:
            base_dir = os.path.join(PROJECT_CONFIG.WORKSPACE_DIR, "case_recommendation", project_id)
            os.makedirs(base_dir, exist_ok=True)
            error_file = os.path.join(base_dir, "error.txt")
            with open(error_file, "w", encoding="utf-8") as f:
                f.write(str(exc))
        except Exception as write_exc:
            LOGGER.exception(f"写入 error.txt 失败: {write_exc}")
        return {"success": False, "error": str(exc)}
