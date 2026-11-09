"""Adapter for the artifact owner's output. Keep the mock ID out of asset logic."""

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class SourceSnapshot:
    filename: str
    content: bytes


def source_snapshot(owner_id: int, artifact_id: str, base_hash: str) -> SourceSnapshot:
    # Replace this provider when the production chat_artifact contract is available.
    from .artifact_mock import check_revision, file_write_lock, mock_artifact, read_original

    source = mock_artifact(owner_id, artifact_id)
    if not source.path.is_file():
        raise HTTPException(404, "原产出物不存在")
    with file_write_lock(source.path):
        content = read_original(source.path)
        check_revision(content, base_hash)
    return SourceSnapshot(f"{source.name}{source.path.suffix}", content)
