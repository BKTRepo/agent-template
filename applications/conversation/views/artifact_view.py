"""Artifact preview/edit/download shared by real outputs and opt-in samples."""

import json
from hashlib import sha256
from mimetypes import guess_type
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from applications.conversation.exceptions import ConversationBusinessError
from applications.conversation.services.artifact_source import resolve_artifact
from applications.conversation.services.artifact_case_groups import with_case_groups
from applications.conversation.services.artifact_documents import MAX_PARAGRAPHS, ParagraphEdit, save_document
from applications.conversation.services.artifact_formats import MAX_TEXT_LENGTH, make_demo_file, ordinary_detail, save_text
from applications.conversation.services.artifact_mock import (
    MAX_FILE_BYTES, asset_path, asset_record_path, check_revision, file_write_lock, mock_artifact, read_original,
    replace_original,
)
from applications.conversation.services.artifact_spreadsheet import CellEdit, save_sheet, sheet_page
from applications.conversation.services.artifact_workbook import (
    MAX_ROWS, TestCase, make_demo_workbook, update_workbook, workbook_detail,
)
from applications.user.models.user_model import User
from applications.wrq.platform_catalog import validate_application_async
from core.responses import SuccessResponse
from services import DependAuth

artifact_router = APIRouter(prefix="/assistant/artifacts", tags=["悬浮对话台-测试产出物"])
ArtifactId = Annotated[str, Field(min_length=1, max_length=128)]
FileHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NO_CACHE = {"Cache-Control": "no-store"}


class DemoRequest(BaseModel):
    kind: str = Field(default="test_cases", max_length=16)


class ArtifactRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: ArtifactId
    base_hash: FileHash


class SaveArtifact(ArtifactRevision):
    cases: list[TestCase] = Field(max_length=MAX_ROWS)


class SaveWord(ArtifactRevision):
    paragraphs: list[ParagraphEdit] = Field(min_length=1, max_length=MAX_PARAGRAPHS)


class SaveSpreadsheet(ArtifactRevision):
    cells: list[CellEdit] = Field(min_length=1, max_length=5000)


class SaveText(ArtifactRevision):
    text: str = Field(max_length=MAX_TEXT_LENGTH)


class ArchiveArtifact(ArtifactRevision):
    name: str = Field(min_length=1, max_length=128)
    application_identify: str = Field(min_length=1, max_length=100)


def result(data):
    response = SuccessResponse(data=data)
    response.headers.update(NO_CACHE)
    return response


@artifact_router.post("/create-demo", summary="产出物-打开当前账号的文件样例")
async def create_demo(data: DemoRequest | None = None, current_user: User = DependAuth):
    artifact = mock_artifact(current_user.id, kind=data.kind if data else "test_cases")
    metadata = await run_in_threadpool(_open_demo, artifact)
    return await _present(artifact, metadata)


def _open_demo(artifact):
    try:
        artifact.path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConversationBusinessError("共享目录不可写") from exc
    with file_write_lock(artifact.path):
        if not artifact.path.exists():
            content = make_demo_workbook() if artifact.kind == "test_cases" else make_demo_file(artifact.kind)
            replace_original(artifact.path, content)
        return _describe(artifact, read_original(artifact.path))


@artifact_router.get("/detail", summary="产出物-读取当前文件和预览数据")
async def detail(artifact_id: ArtifactId, current_user: User = DependAuth):
    artifact = await resolve_artifact(current_user.id, artifact_id)
    metadata = await run_in_threadpool(_read_detail, artifact)
    return await _present(artifact, metadata)


def _read_detail(artifact):
    return _describe(artifact, read_original(artifact.path))


def _describe(artifact, content):
    return workbook_detail(artifact, content) if artifact.kind == "test_cases" else ordinary_detail(artifact, content)


async def _present(artifact, metadata):
    return result(await with_case_groups(artifact, metadata) if artifact.kind == "test_cases" else metadata)


@artifact_router.get("/sheet", summary="产出物-分页读取普通 XLSX 工作表")
async def read_sheet(artifact_id: ArtifactId, base_hash: Annotated[FileHash, Query()], sheet_index: int = Query(ge=0),
               offset: int = Query(default=0, ge=0, le=1048575), column_offset: int = Query(default=0, ge=0, le=16383),
               limit: int = Query(default=25, ge=1, le=50), column_limit: int = Query(default=12, ge=1, le=20),
               current_user: User = DependAuth):
    artifact = await resolve_artifact(current_user.id, artifact_id)
    if artifact.kind != "xlsx":
        raise ConversationBusinessError("该文件使用其他预览方式")
    def read():
        content = read_original(artifact.path)
        check_revision(content, base_hash)
        return sheet_page(content, sheet_index, offset, column_offset, limit, column_limit)
    return result(await run_in_threadpool(read))


@artifact_router.post("/save-content", summary="产出物-按原格式覆盖保存文件")
async def save_content(data: SaveArtifact | SaveWord | SaveSpreadsheet | SaveText, current_user: User = DependAuth):
    artifact = await resolve_artifact(current_user.id, data.artifact_id)
    metadata = await run_in_threadpool(_save, artifact, data)
    if not artifact.id.startswith('mock-'):
        from applications.chat.services.artifacts import count_artifact
        await count_artifact(int(artifact.id), refresh=True)
    return await _present(artifact, metadata)


def _apply_content(artifact, original, data):
    if artifact.kind == "test_cases" and isinstance(data, SaveArtifact):
        return update_workbook(original, data.cases)
    if artifact.kind == "docx" and isinstance(data, SaveWord):
        return save_document(original, data.paragraphs)
    if artifact.kind == "xlsx" and isinstance(data, SaveSpreadsheet):
        return save_sheet(original, data.cells)
    if artifact.file_type not in {"docx", "xlsx"} and isinstance(data, SaveText):
        return save_text(original, data.text, artifact.file_type)
    raise ConversationBusinessError("保存内容与产出物格式不匹配")


def _save(artifact, data):
    with file_write_lock(artifact.path):
        original = read_original(artifact.path)
        check_revision(original, data.base_hash)
        try:
            saved = _apply_content(artifact, original, data)
        except ValueError as exc:
            raise ConversationBusinessError("内容包含文件格式无法保存的字符") from exc
        if len(saved) > MAX_FILE_BYTES:
            raise ConversationBusinessError("修改后的文件超过在线处理上限")
        metadata = _describe(artifact, saved)
        check_revision(read_original(artifact.path), data.base_hash)
        if saved != original:
            replace_original(artifact.path, saved)
    return metadata


@artifact_router.get("/download", summary="产出物-下载整份原格式文件")
async def download(artifact_id: ArtifactId, base_hash: FileHash | None = Query(default=None),
             archived: bool = False, current_user: User = DependAuth):
    artifact = await resolve_artifact(current_user.id, artifact_id)
    if archived and not asset_record_path(artifact).is_file():
        raise ConversationBusinessError("归档文件不存在")
    if archived and not artifact_id.startswith("mock-"):
        raise ConversationBusinessError("已归档原件请从资产管理下载")
    content = await run_in_threadpool(read_original, asset_path(artifact) if archived else artifact.path)
    if base_hash is not None:
        check_revision(content, base_hash)
    media_type = guess_type(artifact.path.name)[0] or "application/octet-stream"
    return Response(content, media_type=media_type, headers={
        **NO_CACHE, "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(artifact.name + '.' + artifact.file_type)}",
    })


def _asset_record(artifact) -> dict:
    path = asset_record_path(artifact)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"included": False}
    except (ValueError, OSError) as exc:
        raise ConversationBusinessError("暂时无法查询样例归档状态") from exc


@artifact_router.get("/asset-status", summary="产出物-查询本地样例是否已归档")
def asset_status(artifact_id: ArtifactId, current_user: User = DependAuth):
    return result(_asset_record(mock_artifact(current_user.id, artifact_id)))


@artifact_router.post("/submit-to-assets", summary="产出物-保存本地资产样例快照")
async def submit_to_assets(data: ArchiveArtifact, current_user: User = DependAuth):
    artifact = mock_artifact(current_user.id, data.artifact_id)
    if not data.name.strip():
        raise ConversationBusinessError("请填写资产名称")
    try:
        await validate_application_async(data.application_identify)
    except ValueError as exc:
        raise ConversationBusinessError("请选择目录中的所属应用") from exc
    return result(await run_in_threadpool(_archive, artifact, data))


def _archive(artifact, data):
    with file_write_lock(artifact.path):
        original = read_original(artifact.path)
        check_revision(original, data.base_hash)
        record = _asset_record(artifact)
        if record["included"]:
            return record
        target = asset_path(artifact)
        record = {
            "included": True, "asset_id": artifact.id, "name": data.name.strip(),
            "application_identify": data.application_identify, "category": artifact.category,
            "file_sha256": sha256(original).hexdigest(),
        }
        replace_original(target, original)
        replace_original(asset_record_path(artifact), json.dumps(record, ensure_ascii=False).encode("utf-8"))
        return record
