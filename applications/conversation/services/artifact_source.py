"""Resolve a generated artifact through its owning, current conversation."""

import re
from pathlib import Path

from applications.chat.models.chat_model import ChatArtifact
from applications.chat.services.artifacts import artifact_path, artifact_root
from applications.conversation.exceptions import ConversationBusinessError
from .artifact_mock import Artifact, mock_artifact


async def resolve_artifact(owner_id: int, artifact_id: str) -> Artifact:
    if artifact_id.startswith("mock-"):
        return mock_artifact(owner_id, artifact_id)
    if not re.fullmatch(r"[1-9][0-9]{0,18}", artifact_id) or int(artifact_id) > 9223372036854775807:
        raise ConversationBusinessError("产出物不存在或无权访问")
    row = await ChatArtifact.filter(id=int(artifact_id), task__status="success",
        task__conversation__user_id=owner_id, task__conversation__state=0).select_related("task__conversation").first()
    if not row or row.task.generation != row.task.conversation.generation:
        raise ConversationBusinessError("产出物不存在或无权访问")
    try:
        raw = artifact_root() / row.storage_key
        if any(part.is_symlink() for part in (raw, *raw.parents)):
            raise ValueError("linked artifact")
        path = artifact_path(row.storage_key)
    except ValueError as exc:
        raise ConversationBusinessError("产出物路径不可用") from exc
    if not path.is_file() or path.is_symlink():
        raise ConversationBusinessError("原产出物不存在或已清理")
    name = Path(row.file_name).stem
    return Artifact(str(row.id), name, path,
                    "test_cases" if row.artifact_type == "test_case" else path.suffix[1:].lower(),
                    row.artifact_type)


def artifact_reference(row):
    # BIGINT stays a string in the browser. Never expose storage_key or server paths.
    return {"artifact_id": str(row.id), "file_name": row.file_name, "artifact_type": row.artifact_type}
