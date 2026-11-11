"""Adapter for the artifact owner's output. Keep the mock ID out of asset logic."""

from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool
from .artifact_source import resolve_artifact


@dataclass(frozen=True)
class SourceSnapshot:
    filename: str
    content: bytes


async def source_snapshot(owner_id: int, artifact_id: str, base_hash: str) -> SourceSnapshot:
    from .artifact_mock import check_revision, file_write_lock, read_original

    source = await resolve_artifact(owner_id, artifact_id)
    def snapshot():
        with file_write_lock(source.path):
            content = read_original(source.path)
            check_revision(content, base_hash)
        return SourceSnapshot(f"{source.name}{source.path.suffix}", content)
    return await run_in_threadpool(snapshot)
