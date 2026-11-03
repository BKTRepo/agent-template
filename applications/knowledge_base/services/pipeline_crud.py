# -*- coding: utf-8 -*-
"""流水线状态 / 历史消息 CRUD 层（rag_pipeline_state / rag_pipeline_history 的唯一数据访问入口）。

替代 JSON 时代的"portalocker 跨进程文件锁 + 全量读-改-写 / JSONL 追加":
- Web 进程与 Celery Worker 进程共享 MySQL, 行级 UPDATE / INSERT 天然原子,
  状态单行表与历史追加表均不再需要跨进程文件锁（persistence.storage_lock 退役）;
- 历史消息读取取最近 N 条（自增 id 倒序后反转回时间升序）, 对外格式沿用
  原契约 "[HH:MM:SS] 消息"; 超限裁剪改为按条数惰性 DELETE（替代原整文件重写）。
"""
from datetime import datetime
from typing import List, Optional

from applications.knowledge_base.models.pipeline_model import (
    RagPipelineHistory,
    RagPipelineState,
)
from configure import LOGGER

# 读取保留最近 N 条（与原 _HISTORY_MAX_ENTRIES 一致）
HISTORY_LIMIT = 200
# 超过该阈值时惰性裁剪（与原 _COMPACTION_THRESHOLD = 4 倍口径一致）
COMPACT_THRESHOLD = HISTORY_LIMIT * 4

_TIME_ONLY_FMT = "%H:%M:%S"


class PipelineCrud:
    """流水线状态（单行表）与历史消息（追加表）CRUD。"""

    # ==================== 运行状态（单行表） ====================

    async def get_start_time(self) -> Optional[datetime]:
        """读取流水线启动时间（空闲/无记录返回 None）。"""
        row = await RagPipelineState.all().order_by("id").first()
        return row.start_time if row else None

    async def set_start_time(self, value: Optional[datetime]) -> None:
        """设置/清空流水线启动时间（get-or-create 单行, 行级 UPDATE 原子）。"""
        row = await RagPipelineState.all().order_by("id").first()
        if row is None:
            await RagPipelineState.create(start_time=value)
        else:
            if row.start_time != value:
                row.start_time = value
                await row.save(update_fields=["start_time"])

    # ==================== 历史消息（追加表） ====================

    async def append_history(self, message: str) -> None:
        """追加一条历史消息（INSERT, 跨进程安全）, 超阈值时惰性裁剪。"""
        await RagPipelineHistory.create(message=message, created_time=datetime.now())
        await self._compact_history_if_needed()

    async def read_history(self, limit: int = HISTORY_LIMIT) -> List[str]:
        """读取最近 *limit* 条历史, 按时间升序、原格式 "[HH:MM:SS] 消息" 返回。"""
        rows = await RagPipelineHistory.all().order_by("-id").limit(limit)
        result: List[str] = []
        for r in reversed(rows):
            t = r.created_time.strftime(_TIME_ONLY_FMT) if r.created_time else ""
            result.append(f"[{t}] {r.message}")
        return result

    async def _compact_history_if_needed(self) -> None:
        """历史条数超阈值时裁剪为最近 HISTORY_LIMIT 条（惰性, 追加时触发）。"""
        count = await RagPipelineHistory.all().count()
        if count <= COMPACT_THRESHOLD:
            return
        keep_ids = await RagPipelineHistory.all().order_by("-id").limit(
            HISTORY_LIMIT,
        ).values_list("id", flat=True)
        deleted = await RagPipelineHistory.exclude(id__in=list(keep_ids)).delete()
        LOGGER.debug(f"流水线历史裁剪: 删除 {deleted} 条, 保留最近 {HISTORY_LIMIT} 条")
