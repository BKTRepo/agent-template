import tempfile
import zipfile
import re
from starlette.background import BackgroundTask
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

from applications.conversation.exceptions import ConversationBusinessError, TestCaseWorkbookFormatError
from applications.conversation.models.asset_model import AssetFile
from applications.conversation.services import asset_service as service
from applications.knowledge_base.services import document_preview as preview
from applications.knowledge_base.services.platform_service import KnowledgeError
from core.responses import SuccessResponse
from services import DependAuth


asset_router = APIRouter(prefix="/api/assets", tags=["资产管理"])
PRIVATE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
SCRIPT_TYPES = {".py", ".js", ".ts", ".sh", ".ps1", ".sql", ".java", ".go", ".rb", ".yaml", ".yml", ".json"}


class ArchiveRequest(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=128)
    base_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = Field(min_length=1, max_length=128)
    skill_classes_id: int = Field(gt=0)
    application_identify: str = Field(min_length=1, max_length=100)
    visibility: Literal["private", "platform"] = "private"

    @field_validator("name", "application_identify")
    @classmethod
    def require_value(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("必填字段不能为空")
        return value


class AssetSelection(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=100)

    @field_validator("asset_ids")
    @classmethod
    def validate_ids(cls, ids):
        if any(asset_id <= 0 for asset_id in ids) or len(ids) != len(set(ids)):
            raise ValueError("资产编号必须为不重复的正整数")
        return ids


def _result(data):
    response = SuccessResponse(data=data)
    response.headers.update(PRIVATE)
    return response


async def _asset(user, asset_id):
    asset = await service.visible_assets(user).filter(id=asset_id).first()
    if asset is None:
        raise ConversationBusinessError("资产不存在或无权访问")
    return asset


async def _file(user, asset_id, file_id):
    await _asset(user, asset_id)
    file = await AssetFile.get_or_none(id=file_id, asset_id=asset_id)
    if file is None:
        raise ConversationBusinessError("附件不存在或无权访问")
    return file, service.file_path(file)


def _fingerprint(path):
    stat = path.stat()
    return str(path), stat.st_size, stat.st_mtime_ns


def _test_cases(file, path):
    # Only the shared workbook adapter may recognize case content. Ordinary Excel stays a sheet preview.
    from applications.conversation.services.artifact_workbook import workbook_detail

    try:
        return workbook_detail(SimpleNamespace(id=str(file.id), name=Path(file.file_name).stem), path.read_bytes())
    except TestCaseWorkbookFormatError:
        return None


@asset_router.get("/overview", summary="资产管理-查询可见资产数量和技能大类")
async def overview(current_user=DependAuth):
    return _result(await service.overview(current_user))


@asset_router.get("/list", summary="资产管理-按技能大类分页查询")
async def list_assets(page: int = Query(1, ge=1), search: str = Query("", max_length=128),
                      skill_classes_id: int | None = Query(None, gt=0), sort: Literal["asc", "desc"] = "desc",
                      current_user=DependAuth):
    return _result(await service.list_page(current_user, page, search, skill_classes_id, sort, False))


@asset_router.get("/recycle-bin", summary="资产管理-查询本人可恢复的资产")
async def recycle_bin(page: int = Query(1, ge=1), current_user=DependAuth):
    return _result(await service.list_page(current_user, page, "", None, "desc", True))


@asset_router.get("/detail", summary="资产管理-查看资产和附件")
async def detail(asset_id: int = Query(..., gt=0), current_user=DependAuth):
    asset = await _asset(current_user, asset_id)
    row, = await service.serialize([asset], current_user)
    return _result({**row, "files": await service.asset_files(asset_id)})


@asset_router.get("/source-status", summary="资产管理-按产出物编号查询纳入状态")
async def source_status(artifact_id: str = Query(..., min_length=1, max_length=128), current_user=DependAuth):
    return _result(await service.asset_status(current_user, artifact_id))


@asset_router.post("/create", summary="资产管理-归档整份产出物")
async def create(data: ArchiveRequest, current_user=DependAuth):
    return _result(await service.archive(current_user, data))


@asset_router.post("/move-to-recycle-bin", summary="资产管理-将所选资产移入回收站")
async def move_to_recycle(data: AssetSelection, current_user=DependAuth):
    return _result({"changed": await service.change_recycle_state(current_user, data.asset_ids, restore=False)})


@asset_router.post("/restore", summary="资产管理-恢复回收站资产")
async def restore(data: AssetSelection, current_user=DependAuth):
    return _result({"changed": await service.change_recycle_state(current_user, data.asset_ids, restore=True)})


@asset_router.post("/delete-recycled", summary="资产管理-彻底删除本人回收站资产及文件")
async def delete_recycled(data: AssetSelection, current_user=DependAuth):
    return _result({"changed": await service.delete_recycled(data.asset_ids, user=current_user)})


@asset_router.get("/preview", summary="资产管理-识别原文件预览方式")
async def preview_file(asset_id: int = Query(..., gt=0), file_id: int = Query(..., gt=0), current_user=DependAuth):
    file, path = await _file(current_user, asset_id, file_id)
    suffix = Path(file.file_name).suffix.lower()
    data = {"format": suffix.lstrip("."), "viewer": "unsupported"}
    try:
        if suffix == ".xlsx":
            cases = await run_in_threadpool(_test_cases, file, path) if file.size_bytes <= 10 * 1024 * 1024 else None
            if cases is not None:
                from applications.conversation.services.artifact_case_groups import with_case_groups
                source = SimpleNamespace(id=f"asset-file-{file.id}", path=path)
                cases = await with_case_groups(source, cases)
                await _asset(current_user, asset_id)
                return _result({**data, "viewer": "case", "case_artifact": cases})
            data.update(viewer="spreadsheet", sheets=await run_in_threadpool(preview.workbook_metadata, _fingerprint(path)))
        elif suffix in {".docx", ".pdf"}:
            data["viewer"] = "pdf"
        elif suffix in SCRIPT_TYPES or suffix in {".txt", ".csv", ".md"}:
            data["viewer"] = "code" if suffix in SCRIPT_TYPES else ("markdown" if suffix == ".md" else "text")
            def read_text():
                with path.open("rb") as stream:
                    content = stream.read(512 * 1024)
                return content.decode("utf-8-sig", errors="replace")
            data.update(text=await run_in_threadpool(read_text), truncated=file.size_bytes > 512 * 1024)
    except KnowledgeError as exc:
        raise ConversationBusinessError(str(exc)) from exc
    await _asset(current_user, asset_id)
    return _result(data)


@asset_router.get("/preview-pdf", summary="资产管理-读取 PDF 或 Word 预览")
async def preview_pdf(asset_id: int = Query(..., gt=0), file_id: int = Query(..., gt=0), current_user=DependAuth):
    _, path = await _file(current_user, asset_id, file_id)
    try:
        pdf = await preview.render_pdf(path, _fingerprint(path))
    except KnowledgeError as exc:
        raise ConversationBusinessError(str(exc)) from exc
    await _asset(current_user, asset_id)
    return FileResponse(pdf, media_type="application/pdf", headers=PRIVATE)


@asset_router.get("/preview-sheet", summary="资产管理-分页读取 Excel 工作表")
async def preview_sheet(asset_id: int = Query(..., gt=0), file_id: int = Query(..., gt=0),
                        sheet_index: int = Query(..., ge=0), offset: int = Query(0, ge=0),
                        column_offset: int = Query(0, ge=0), current_user=DependAuth):
    _, path = await _file(current_user, asset_id, file_id)
    if path.suffix != ".xlsx":
        raise ConversationBusinessError("该文件不是 Excel 工作簿")
    try:
        data = await run_in_threadpool(preview.workbook_page, _fingerprint(path), sheet_index, offset, 100, column_offset, 50)
    except KnowledgeError as exc:
        raise ConversationBusinessError(str(exc)) from exc
    await _asset(current_user, asset_id)
    return _result(data)


@asset_router.get("/download", summary="资产管理-下载整份归档文件")
async def download(asset_id: int = Query(..., gt=0), file_id: int = Query(..., gt=0), current_user=DependAuth):
    file, path = await _file(current_user, asset_id, file_id)
    return FileResponse(path, filename=file.file_name, media_type="application/octet-stream", headers=PRIVATE)


@asset_router.post("/export", summary="资产管理-打包导出所选资产原文件")
async def export(data: AssetSelection, current_user=DependAuth):
    rows = await service.visible_assets(current_user).filter(id__in=data.asset_ids).order_by("id")
    if len(rows) != len(data.asset_ids):
        raise ConversationBusinessError("资产不存在或无权访问")
    files = await AssetFile.filter(asset_id__in=data.asset_ids).order_by('asset_id', 'id')
    if not files or sum(file.size_bytes for file in files) > 200 * 1024 * 1024:
        raise ConversationBusinessError("请选择有文件且合计不超过200MB的资产")
    def package():
        directory = service.asset_root() / '.exports'
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, suffix='.zip', delete=False) as temporary:
            target = Path(temporary.name)
        try:
            with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for file in files:
                    name = re.sub(r'[\\/\x00-\x1f\x7f]', '_', file.file_name)
                    archive.write(service.storage_path(file.storage_key), f'{file.asset_id}/{file.id}-{name}')
            return target
        except Exception:
            target.unlink(missing_ok=True)
            raise
    target = await run_in_threadpool(package)
    try:
        if await service.visible_assets(current_user).filter(id__in=data.asset_ids).count() != len(data.asset_ids):
            raise ConversationBusinessError("资产权限或状态已变化，请重新选择")
        return FileResponse(target, filename='资产原文件.zip', media_type='application/zip', headers=PRIVATE,
                            background=BackgroundTask(target.unlink, missing_ok=True))
    except BaseException:
        target.unlink(missing_ok=True)
        raise
