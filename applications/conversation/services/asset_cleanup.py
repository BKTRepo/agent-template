from datetime import datetime, timezone

from tortoise.exceptions import OperationalError
from tortoise.timezone import now

from applications.conversation.models.asset_model import Asset
from configure import LOGGER

from .asset_service import delete_recycled, recovery_period


async def cleanup_expired_assets():
    cutoff = now() - recovery_period()
    last_id = 0
    while True:
        try:
            ids = await Asset.filter(deleted_at__lte=cutoff, id__gt=last_id).order_by("id").limit(100).values_list("id", flat=True)
        except OperationalError:
            LOGGER.warning("资产过期清理暂不可用，请检查资产表迁移和数据库连接")
            return
        if not ids:
            return
        for asset_id in ids:
            try:
                await delete_recycled([asset_id], expired_before=cutoff)
            except Exception:
                LOGGER.exception("资产 {} 清理失败，下次任务继续重试", asset_id)
        last_id = ids[-1]


def register_asset_cleanup(scheduler):
    scheduler.add_job(cleanup_expired_assets, "interval", minutes=5, id="expired-assets-cleanup",
                      next_run_time=datetime.now(timezone.utc), max_instances=1, coalesce=True)
