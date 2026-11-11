from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q, Subquery
from tortoise.functions import Count
from tortoise.timezone import now
from tortoise.transactions import in_transaction

from applications.conversation.models.asset_model import Asset, AssetFile
from applications.user.models.user_model import User
from applications.wrq.agent.models.agent_model import DeveloperSkillClass
from applications.wrq.platform_catalog import validate_application_async
from configure import PROJECT_CONFIG

from .asset_source import source_snapshot


PAGE_SIZE = 10

def recovery_period():
    return timedelta(days=PROJECT_CONFIG.ASSET_RECYCLE_RETENTION_DAYS)


def visible_assets(user, *, recycle=False):
    if recycle:
        return Asset.filter(created_by=user.id, deleted_at__gt=now() - recovery_period())
    return Asset.filter(Q(created_by=user.id) | Q(visibility="platform"), deleted_at__isnull=True)


async def overview(user):
    counts = await visible_assets(user).group_by("skill_classes_id").annotate(count=Count("id")).values("skill_classes_id", "count")
    by_class = {row["skill_classes_id"]: row["count"] for row in counts}
    classes = await DeveloperSkillClass.all().order_by("id")
    return {
        "total": sum(by_class.values()), "recycle_count": await visible_assets(user, recycle=True).count(),
        "recycle_days": PROJECT_CONFIG.ASSET_RECYCLE_RETENTION_DAYS,
        "classes": [{"id": row.id, "name": row.name, "count": by_class.get(row.id, 0), "enabled": row.is_enabled}
                    for row in classes if row.is_enabled or row.id in by_class],
    }


async def serialize(rows, user):
    classes = await DeveloperSkillClass.in_bulk({row.skill_classes_id for row in rows})
    owners = await User.in_bulk({row.created_by for row in rows})
    return [{
        "id": row.id, "name": row.name, "skill_classes_id": row.skill_classes_id,
        "class_name": classes[row.skill_classes_id].name if row.skill_classes_id in classes else "历史技能类",
        "application_identify": row.application_identify,
        "creator_name": owners[row.created_by].alias if row.created_by in owners else "历史用户",
        "visibility": row.visibility, "can_manage": row.created_by == user.id,
        "created_time": row.created_time.isoformat(),
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        "restore_until": (row.deleted_at + recovery_period()).isoformat() if row.deleted_at else None,
    } for row in rows]


async def list_page(user, page, search, class_id, sort, recycle):
    query = visible_assets(user, recycle=recycle)
    if class_id is not None:
        query = query.filter(skill_classes_id=class_id)
    if keyword := search.strip():
        owners = User.filter(Q(alias__icontains=keyword) | Q(username__icontains=keyword)).values_list("id", flat=True)
        query = query.filter(Q(name__icontains=keyword) | Q(created_by__in=Subquery(owners)))
    total = await query.count()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages)
    order = ("-deleted_at", "-id") if recycle else (("created_time", "id") if sort == "asc" else ("-created_time", "-id"))
    rows = await query.order_by(*order).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    return {"items": await serialize(rows, user), "total": total, "page": page, "pages": pages}


def asset_root():
    return Path(PROJECT_CONFIG.OUTPUT_DIR).resolve() / "assets"


def storage_path(key):
    root = asset_root().resolve()
    path = root / key
    if path.parent != root or path.is_symlink():
        raise HTTPException(404, "归档路径无效")
    return path


def file_path(file):
    path = storage_path(file.storage_key)
    if not path.is_file():
        raise HTTPException(404, "归档文件不存在")
    return path


async def asset_files(asset_id):
    return await AssetFile.filter(asset_id=asset_id).order_by("id").values("id", "file_name", "size_bytes")


async def asset_status(user, artifact_id):
    asset = await Asset.get_or_none(created_by=user.id, source_artifact_id=artifact_id)
    return {"included": bool(asset and not asset.deleted_at), "recycled": bool(asset and asset.deleted_at),
            "asset_id": asset.id if asset else None, "files": await asset_files(asset.id) if asset and not asset.deleted_at else []}


def _persist(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as file:
        file.write(content)


async def archive(user, data):
    existing = await asset_status(user, data.artifact_id)
    if existing["included"]:
        return existing
    if existing["recycled"]:
        raise HTTPException(409, "产出物已在回收站，请先恢复资产")
    if not await DeveloperSkillClass.filter(id=data.skill_classes_id, is_enabled=True).exists():
        raise HTTPException(422, "请选择已启用的技能大类")
    try:
        await validate_application_async(data.application_identify)
    except ValueError as exc:
        raise HTTPException(422, "请选择目录中的所属应用") from exc
    source = await run_in_threadpool(source_snapshot, user.id, data.artifact_id, data.base_hash)
    key = uuid4().hex + Path(source.filename).suffix.lower()
    target = asset_root() / key
    try:
        await run_in_threadpool(_persist, target, source.content)
        async with in_transaction() as db:
            asset = await Asset.create(using_db=db, name=data.name, skill_classes_id=data.skill_classes_id,
                application_identify=data.application_identify, created_by=user.id, visibility=data.visibility,
                source_artifact_id=data.artifact_id)
            file = await AssetFile.create(using_db=db, asset_id=asset.id, file_name=source.filename,
                storage_key=key, size_bytes=len(source.content))
    except IntegrityError as exc:
        await run_in_threadpool(target.unlink, missing_ok=True)
        existing = await asset_status(user, data.artifact_id)
        if existing["included"]:
            return existing
        if existing["recycled"]:
            raise HTTPException(409, "产出物已在回收站，请先恢复资产") from exc
        raise HTTPException(409, "暂时无法归档此产出物，请重试") from exc
    except Exception:
        await run_in_threadpool(target.unlink, missing_ok=True)
        raise
    return {"included": True, "recycled": False, "asset_id": asset.id,
            "files": [{"id": file.id, "file_name": file.file_name, "size_bytes": file.size_bytes}]}


async def change_recycle_state(user, ids, *, restore):
    operation_time = now()
    async with in_transaction() as db:
        query = Asset.filter(id__in=ids, created_by=user.id).using_db(db)
        rows = await query.order_by("id").select_for_update()
        if len(rows) != len(ids):
            raise HTTPException(404, "资产不存在或无权操作")
        if restore and any(row.deleted_at and row.deleted_at <= operation_time - recovery_period() for row in rows):
            raise HTTPException(409, "资产已超过可恢复期限")
        if restore:
            files = await AssetFile.filter(asset_id__in=ids).using_db(db)
            if any(not storage_path(file.storage_key).is_file() for file in files):
                raise HTTPException(409, "归档文件已丢失，无法恢复")
            return await query.filter(deleted_at__isnull=False).update(deleted_at=None)
        return await query.filter(deleted_at__isnull=True).update(deleted_at=operation_time)


async def delete_recycled(ids, *, user=None, expired_before=None):
    async with in_transaction() as db:
        query = Asset.filter(id__in=ids, deleted_at__isnull=False).using_db(db)
        if user is not None:
            query = query.filter(created_by=user.id)
        if expired_before is not None:
            query = query.filter(deleted_at__lte=expired_before)
        rows = await query.order_by("id").select_for_update()
        if user is not None and len(rows) != len(ids):
            raise HTTPException(404, "只能彻底删除本人的回收站资产")
        eligible = [row.id for row in rows]
        if not eligible:
            return 0
        files = AssetFile.filter(asset_id__in=eligible).using_db(db)
        paths = [storage_path(file.storage_key) for file in await files]
        try:
            for path in paths:
                await run_in_threadpool(path.unlink, missing_ok=True)
        except OSError as exc:
            raise HTTPException(503, "暂时无法删除归档文件，请稍后重试") from exc
        await files.delete()
        return await query.filter(id__in=eligible).delete()
