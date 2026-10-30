# -*- coding: utf-8 -*-
"""
@Author  : weixianzhe & zhoushengjie
@Project : KeenRobot
@Module  : task_test_case_gen.py
@DateTime: 2026/6/15

Celery 异步任务：测试用例生成。
接口收到请求后立即返回 task_id，由 Celery Worker 在后台执行：
  1. 将已保存的 docx 转换为 md
  2. 调用 Claude Agent SDK 生成测试用例（多模型轮询）
  3. 更新 TestCaseTask 记录状态
"""
import os

from celery_scheduler.celery_base import init_tortoise_orm
from celery_scheduler.celery_worker import celery
from configure import LOGGER


async def _generate_test_cases_impl(
    task_id: int,
    folder_path: str,
    source_filenames: list[str],
) -> dict:
    """异步执行体：在 Celery Worker 的 event loop 中运行。"""
    await init_tortoise_orm()

    from applications.weixianzhe.models.test_case_task_model import TestCaseTask
    from applications.weixianzhe.services.claude_generator import ClaudeTestCaseGenerator
    from common.file_converter import convert_file_to_md

    record = await TestCaseTask.get_or_none(id=task_id)
    if record is None:
        raise RuntimeError(f"任务记录不存在: id={task_id}")

    # ---- 更新状态为 generating ----
    record.status = "generating"
    await record.save(update_fields=["status"])

    # ---- 步骤1: 将已保存的 docx 转换为 md ----
    md_filenames: list[str] = []
    for filename in source_filenames:
        source_path = os.path.join(folder_path, filename)
        if not os.path.isfile(source_path):
            raise RuntimeError(f"源文件不存在: {source_path}")

        try:
            convert_file_to_md(source_path)
        except Exception as exc:
            LOGGER.exception("文件转换失败: %s", exc)
            raise RuntimeError(f"文件「{filename}」转换失败: {exc}")

        # 转换成功后删除原 docx
        md_filename = filename.rsplit(".", 1)[0] + ".md"
        md_path = os.path.join(folder_path, md_filename)
        if os.path.isfile(md_path):
            md_filenames.append(md_filename)
            os.remove(source_path)

    if not md_filenames:
        raise RuntimeError("所有文件转换后均未生成 md 文件")

    # ---- 步骤2: 调用 Claude Agent SDK 生成测试用例（多模型轮询） ----
    generator = ClaudeTestCaseGenerator()
    result = await generator.generate(source_path=folder_path, output_dir=folder_path)

    # ---- 步骤3: 校验产物 ----
    md_output_path = os.path.join(folder_path, "02-功能测试用例.md")
    if not os.path.isfile(md_output_path):
        LOGGER.warning("Agent 执行完毕但未生成产物, result_text 前200字符: %s", result[:200])
        raise RuntimeError("Agent 执行完成但未生成 02-功能测试用例.md")

    # ---- 更新状态为 success ----
    record.status = "success"
    await record.save(update_fields=["status"])

    LOGGER.info(f"【Celery】测试用例生成任务完成: task_id={task_id}")
    return {"success": True, "result": result[:200]}


@celery.task(
    name="celery_scheduler.tasks.task_test_case_gen.generate_test_cases_task",
    soft_time_limit=1800,
    time_limit=2000,
)
async def generate_test_cases_task(
    task_id: int,
    folder_path: str,
    source_filenames: list[str],
) -> dict:
    """Celery 入口：根据 task_id 后台执行测试用例生成。

    Args:
        task_id: TestCaseTask 表的主键 ID。
        folder_path: 任务输出文件夹路径（已保存 docx）。
        source_filenames: 已保存的 docx 文件名列表。
    """
    try:
        return await _generate_test_cases_impl(task_id, folder_path, source_filenames)
    except Exception as exc:
        LOGGER.exception("测试用例生成任务失败: %s", exc)
        # 更新任务状态为 failed
        try:
            await init_tortoise_orm()
            from applications.weixianzhe.models.test_case_task_model import TestCaseTask
            record = await TestCaseTask.get_or_none(id=task_id)
            if record:
                record.status = "failed"
                record.error_reason = str(exc)[:500]
                await record.save(update_fields=["status", "error_reason"])
        except Exception as db_exc:
            LOGGER.exception("更新任务失败状态异常: %s", db_exc)
        return {"success": False, "error": str(exc)}
