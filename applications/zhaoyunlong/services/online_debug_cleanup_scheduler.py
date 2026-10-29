"""在线调试过期结果的定时清理任务。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from applications.zhaoyunlong.models.online_debug_run_model import OnlineDebugRun

from .online_debug_service import OnlineDebugService


async def cleanup_expired_online_debug_data() -> None:
    """先按任务表删除过期结果目录，再删除对应任务记录。"""
    now = datetime.now()
    expired_run_ids = await OnlineDebugRun.filter(expires_at__lte=now).values_list("run_id", flat=True)
    service = OnlineDebugService()
    # 任务表的 expires_at 是清理主依据，手动调整过期时间时也能同步删除目录。
    await asyncio.to_thread(service.remove_run_directories, expired_run_ids)
    # 同时清理没有任务表记录、但 metadata.json 本身已过期的孤儿目录。
    await asyncio.to_thread(service.cleanup_expired_runs)
    await OnlineDebugRun.filter(expires_at__lte=now).delete()


def create_online_debug_cleanup_scheduler() -> AsyncIOScheduler:
    """创建每天北京时间凌晨三点执行一次的在线调试清理调度器。"""
    scheduler = AsyncIOScheduler(timezone=ZoneInfo("Asia/Shanghai"))
    scheduler.add_job(
        cleanup_expired_online_debug_data,
        trigger="cron",
        hour=3,  # 凌晨3点删除
        minute=0,
        # trigger="interval",  # 临时测试定时任务 30秒后删文件和表数据
        # seconds=30,
        id="online-debug-expired-data-cleanup",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=60 * 60,
    )
    return scheduler
