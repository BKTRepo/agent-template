"""Adapter for the artifact owner's output. Keep the mock ID out of asset logic."""

from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool
from .artifact_source import resolve_artifact


@dataclass(frozen=True)
class SourceSnapshot:
    filename: str
    content: bytes
    groups: list | None = None


async def source_snapshot(owner_id: int, artifact_id: str, base_hash: str) -> SourceSnapshot:
    from .artifact_mock import check_revision, file_write_lock, read_original

    source = await resolve_artifact(owner_id, artifact_id)
    def snapshot():
        with file_write_lock(source.path):
            content = read_original(source.path)
            check_revision(content, base_hash)
        return SourceSnapshot(f"{source.name}{source.path.suffix}", content)
    result = await run_in_threadpool(snapshot)
    if source.kind != "test_cases":
        return result
    from .artifact_case_groups import with_case_groups
    from .artifact_workbook import workbook_detail
    from applications.conversation.exceptions import ConversationBusinessError

    metadata = await run_in_threadpool(workbook_detail, source, result.content)
    grouped = await with_case_groups(source, metadata)
    if grouped["grouping_status"] != "complete":
        raise ConversationBusinessError("测试要点归纳失败，请重新打开产出物后重试纳入")
    return SourceSnapshot(result.filename, result.content, grouped["groups"])
