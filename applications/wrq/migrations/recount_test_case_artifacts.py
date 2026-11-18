"""Recount retained case workbooks across all sheets. Use --apply to persist totals."""

import argparse
import asyncio
import json

from tortoise import Tortoise

from applications.chat.models.chat_model import ChatArtifact, ChatArtifactCount
from applications.chat.services.artifacts import artifact_path, count_artifact, count_cases
from applications.wrq.database import wrq_connections
from configure import PROJECT_CONFIG


async def recount(*, apply=False):
    totals = {"checked": 0, "updated": 0, "skipped": 0, "failed": 0}
    cursor = 0
    while True:
        rows = await ChatArtifact.filter(
            artifact_type="test_case", task__status="success", id__gt=cursor,
        ).order_by("id").limit(100)
        if not rows:
            break
        for row in rows:
            cursor = row.id
            try:
                path = artifact_path(row.storage_key)
                if not path.is_file():
                    totals["skipped"] += 1
                    print(json.dumps({"artifact_id": row.id, "skipped": "原产物已清理"}, ensure_ascii=False))
                    continue
                expected = await asyncio.to_thread(count_cases, path)
                previous = await ChatArtifactCount.get_or_none(artifact_id=row.id)
                totals["checked"] += 1
                print(json.dumps({"artifact_id": row.id, "previous": previous.quantity if previous else None,
                                  "all_sheets": expected}, ensure_ascii=False))
                if apply:
                    # Refresh replaces the existing metric under its unique artifact key.
                    await count_artifact(row.id, refresh=True)
                    saved = await ChatArtifactCount.get_or_none(artifact_id=row.id)
                    if not saved or saved.status != "counted" or saved.quantity != expected:
                        raise ValueError("统计回写失败或源文件正在修改，请重试")
                    totals["updated"] += 1
            except Exception as exc:
                totals["failed"] += 1
                print(json.dumps({"artifact_id": row.id, "error": str(exc)}, ensure_ascii=False))
    print(json.dumps(totals, ensure_ascii=False))
    return totals


async def main(*, apply=False):
    await Tortoise.init(config={
        "connections": wrq_connections(PROJECT_CONFIG.DATABASE_CONNECTIONS),
        "apps": {"models": {"models": PROJECT_CONFIG.APPLICATIONS_MODELS, "default_connection": "default"}},
        "use_tz": False, "timezone": "Asia/Shanghai",
    })
    try:
        totals = await recount(apply=apply)
        if totals["failed"]:
            raise SystemExit(1)
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(apply=parser.parse_args().apply))
