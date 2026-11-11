"""产物统计：测试用例以“用例编号”非空的行计数。"""

import asyncio
from pathlib import Path

from openpyxl import load_workbook
from tortoise.transactions import in_transaction

from applications.chat.models.chat_model import ChatArtifact, ChatArtifactCount, ChatSkillCall


def artifact_root():
    return (Path(__file__).resolve().parents[1] / "chat_results").resolve()


def artifact_path(key: str) -> Path:
    root = artifact_root()
    path = (root / key).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("产物路径无效")
    return path


def count_cases(path: Path) -> int:
    from applications.conversation.services.artifact_workbook import read_workbook
    from applications.conversation.exceptions import TestCaseWorkbookFormatError
    try:
        book, cases, _, _ = read_workbook(path.read_bytes())
        book.close()
        return len(cases)
    except TestCaseWorkbookFormatError:
        pass
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        count = 0
        found_header = False
        for sheet in workbook.worksheets:
            column = None
            for row in sheet.iter_rows(values_only=True):
                if column is None:
                    matches = [i for i, value in enumerate(row) if str(value or "").strip() == "用例编号"]
                    if len(matches) > 1:
                        raise ValueError("同一工作表有多个用例编号列")
                    if matches:
                        column = matches[0]
                        found_header = True
                    continue
                value = row[column] if column < len(row) else None
                if isinstance(value, str) and value.startswith('='):
                    raise ValueError('用例编号包含公式，无法准确统计')
                if value is not None and str(value).strip() and str(value).strip() != "用例编号":
                    count += 1
        if not found_header:
            raise ValueError("未找到用例编号列")
        return count
    finally:
        workbook.close()


async def count_artifact(artifact_id: int, *, refresh=False):
    artifact = await ChatArtifact.get_or_none(id=artifact_id).select_related("task")
    if not artifact or artifact.task.status != "success":
        return
    previous = await ChatArtifactCount.get_or_none(artifact_id=artifact_id)
    if artifact.count_status == 'counted' and previous and previous.details and not refresh:
        return
    try:
        from applications.user.models.user_model import User
        from applications.wrq.agent.models.agent_model import Skill
        conversation = await artifact.task.conversation
        owner = await User.get(id=conversation.user_id)
        calls = await ChatSkillCall.filter(task_id=artifact.task_id)
        called_skills = await Skill.filter(id__in=[call.skill_id for call in calls])
        path = artifact_path(artifact.storage_key)
        if not path.is_file():
            raise ValueError("产物文件不存在")
        quantity = await asyncio.to_thread(count_cases, path) if artifact.artifact_type == "test_case" else 1
        kind = artifact.artifact_type
        if kind != 'test_case' and path.suffix.lower() == '.xlsx' and any(skill.skill_classes_id == 3 for skill in called_skills):
            from applications.conversation.services.asset_quantity import file_quantity
            quantity, _ = await asyncio.to_thread(file_quantity, path, 3)
            kind = 'test_data'
        details = {'artifact_type': kind, 'file_name': artifact.file_name, 'employee_no': owner.username,
            'department': None, 'skill_ids': sorted({call.skill_id for call in calls}),
            'skill_name': '、'.join(dict.fromkeys(call.skill_name_snapshot or next((s.name for s in called_skills if s.id == call.skill_id), str(call.skill_id)) for call in calls)),
            'duration_ms': max(0, int((artifact.task.finished_at - artifact.task.started_at).total_seconds() * 1000)) if artifact.task.started_at and artifact.task.finished_at else None}
        async with in_transaction() as conn:
            current = await ChatArtifact.filter(id=artifact_id).using_db(conn).select_for_update().first()
            if not current or (current.count_status == "counted" and previous and previous.details and not refresh):
                return
            # 写入统计与状态在同一事务；唯一键保证重复执行不会重复统计。
            metric, _ = await ChatArtifactCount.get_or_create(artifact_id=artifact_id,
                defaults={"quantity": quantity, "status": "counted", "generated_at": artifact.task.finished_at, "details": details}, using_db=conn)
            if refresh or metric.status != 'counted' or not metric.details:
                metric.quantity, metric.status, metric.error = quantity, 'counted', None
                metric.generated_at = artifact.task.finished_at
                metric.details = details
                await metric.save(using_db=conn, update_fields=['quantity', 'status', 'error', 'generated_at', 'details'])
            current.count_status = "counted"
            current.count_error = None
            await current.save(using_db=conn, update_fields=["count_status", "count_error"])
    except Exception as exc:
        current = await ChatArtifact.get_or_none(id=artifact_id)
        if current and (current.count_status != "counted" or refresh):
            current.retry_count += 1
            current.count_status = "needs_review" if current.retry_count >= 3 else "failed"
            current.count_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            await current.save(update_fields=["retry_count", "count_status", "count_error"])
            if refresh:
                await ChatArtifactCount.filter(artifact_id=artifact_id).update(status="failed", quantity=None, error=current.count_error)
