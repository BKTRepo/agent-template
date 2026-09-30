# -*- coding: utf-8 -*-
"""RAG 文档 CRUD 层（keenrobot_rag_document 表的唯一数据访问入口）。

替代 JSON 时代的"跨进程锁 + 全量读-改-写"（persistence.storage_lock +
doc_status.json）: Web 进程与 Celery Worker 进程共享 MySQL, 行级 UPDATE +
事务 + 条件更新天然防丢更新, portalocker 文件锁在文档存储上退役。

守卫语义与原 RagDocumentService 完全一致: 已标记"用户取消"的文档,
Worker 的进度/失败写回不得将其复活或篡改摘要（显式重置传 bypass_guard=True）。
"""
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from applications.jiayueyang.models.rag_document_model import RagDocument
from applications.jiayueyang.services.scaffold import ScaffoldCrud
from configure import LOGGER
from core.exceptions import DataAlreadyExistsException


class RagDocumentCrud(ScaffoldCrud[RagDocument, Dict, Dict]):
    """文档表 CRUD（含防覆盖守卫、取消与巡检支撑方法）。"""

    # 处理中状态集合（与 RagDocumentService.ACTIVE_STATUSES 同口径）
    ACTIVE_STATUSES = (
        "queued", "splitting", "parsing", "terminology",
        "analyzing", "chunking", "embedding",
    )
    # queued 之外的中间态（巡检候选只取这些, queued 按时长另行判定）
    ACTIVE_PROCESSING_STATUSES = ACTIVE_STATUSES[1:]
    DELETING_STATUS = "deleting"

    def __init__(self):
        super().__init__(model=RagDocument)

    # ==================== 查询 ====================

    async def get_by_job_id(self, job_id: str) -> Optional[RagDocument]:
        """按 job_id 获取文档（不存在返回 None）。"""
        return await self.model.filter(job_id=job_id).first()

    async def mark_deleting(self, job_ids: List[str]) -> List[RagDocument]:
        """在事务内把文档标记为 deleting，并返回删除所需的文档快照。

        这里只改变 MySQL 状态，不物理删除文档记录；文件和向量由后续
        Celery 删除任务清理。行级锁保证同一文档不会被并发删除流程重复领取。
        """
        ids = list(dict.fromkeys(j.strip() for j in job_ids if j and j.strip()))
        if not ids:
            return []

        async with in_transaction():
            docs = await self.model.filter(job_id__in=ids).select_for_update()
            if not docs:
                return []

            deletable = [d for d in docs if d.status != self.DELETING_STATUS]
            if deletable:
                deletable_ids = [d.job_id for d in deletable]
                await self.model.filter(job_id__in=deletable_ids).update(
                    status=self.DELETING_STATUS,
                    cancel_requested=True,
                    deleting_retry_count=0,
                    deletion_retryable=True,
                    deletion_error_type=None,
                    summary="删除任务已提交，等待后台清理",
                    error_trace=None,
                )
                for doc in deletable:
                    doc.status = self.DELETING_STATUS
                    doc.cancel_requested = True

            return list(docs)

    async def list_all(self) -> List[RagDocument]:
        """全部文档（按创建时间倒序）。"""
        return await self.model.all().order_by("-created_time")

    async def complete_doc_ids(self) -> Set[str]:
        """已 complete 的文档 job_id 集合（术语索引新鲜度判定用）。"""
        rows = await self.model.filter(status="complete").values_list("job_id", flat=True)
        return set(rows)

    _TIME_FMT = "%Y-%m-%d %H:%M:%S"

    def _allowed_fields(self) -> Set[str]:
        """模型可写字段白名单（防御性过滤未知键, 如 id/markdown/created_at）。"""
        meta = self.model._meta
        return set(meta.fields_map.keys()) - {"id", "created_time", "updated_time"}

    def _convert_time_field(self, value: Any) -> Any:
        """时间字段兼容转换: 流水线沿用字符串写时间（now_time()/"" 清零）,
        统一转为 DatetimeField 需要的 datetime（空串/不可解析 → None）。"""
        if isinstance(value, datetime) or value is None:
            return value
        if isinstance(value, str):
            if not value.strip():
                return None
            try:
                return datetime.strptime(value, self._TIME_FMT)
            except ValueError:
                LOGGER.warning(f"无法解析的时间字段值, 置空处理: {value!r}")
                return None
        return value

    # 数值列类名集合: 流水线有"空串清零"惯例（为时间字段设计）, 但空串写入
    # 数值列会在驱动层触发 float('')/int('') 崩溃——v0.11 增量更新的阶段计时
    # 清零曾因此中断在 prev 归档之后, 留下"目录已归档而文档行未写入"的残缺
    # 状态（术语索引与产物路径全部失联）。数值列空串在此统一转 None
    _NUMERIC_FIELD_TYPES = frozenset((
        "IntField", "BigIntField", "SmallIntField", "FloatField", "DecimalField",
    ))

    def sanitize(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """按模型字段白名单过滤写入字典（未知键丢弃）, 并做字段类型转换:
        时间字段空串/字符串 → datetime（None 兜底）; 数值字段空串 → None。"""
        meta = self.model._meta
        allowed = self._allowed_fields()
        clean: Dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed:
                continue
            field_obj = meta.fields_map.get(key)
            cls_name = field_obj.__class__.__name__
            if cls_name == "DatetimeField":
                value = self._convert_time_field(value)
            elif value == "" and cls_name in self._NUMERIC_FIELD_TYPES:
                value = None
            clean[key] = value
        dropped = set(fields.keys()) - set(clean.keys())
        if dropped:
            LOGGER.debug(f"文档写入忽略非模型字段: {sorted(dropped)}")
        return clean

    # ==================== 写入 ====================

    async def create_document(self, entry: Dict[str, Any]) -> RagDocument:
        """创建文档条目: 重名查重（大小写不敏感）+ 唯一约束兜底。

        MySQL utf8mb4 默认排序规则(ci)下 UNIQUE(filename) 即大小写不敏感唯一,
        与原 JSON 侧锁内重名校验语义一致; 预检查先行给出友好错误,
        并发窗口由唯一约束兜底。

        :raises DataAlreadyExistsException: 已存在同名文档
        """
        entry = self.sanitize(entry)
        filename = entry.get("filename") or ""
        if filename and await self.model.filter(filename=filename).exists():
            raise DataAlreadyExistsException(
                message=f"文件名 '{filename}' 已存在, 请修改文件名后上传"
            )
        try:
            return await self.create(entry)
        except IntegrityError as e:
            LOGGER.warning(f"创建文档触发唯一约束（并发同名上传）: {filename}\n{traceback.format_exc()}")
            raise DataAlreadyExistsException(
                message=f"文件名 '{filename}' 已存在, 请修改文件名后上传"
            ) from e

    @staticmethod
    def _is_cancelled(doc: RagDocument) -> bool:
        """防覆盖守卫判定: 记录是否为"用户取消"终态。

        取消以 cancel_requested 字段驱动（码化, 不依赖文案）;
        摘要比对仅为旧数据（迁移自 JSON 的历史记录）兼容兜底。
        """
        if doc.cancel_requested:
            return True
        return doc.status == "failed" and doc.summary == "用户取消"

    async def merge_update(
            self,
            job_id: str,
            fields: Dict[str, Any],
            bypass_guard: bool = False,
    ) -> Optional[RagDocument]:
        """行级归并更新: 事务内 SELECT FOR UPDATE + 防覆盖守卫 + 字段合并。

        等价于原 save_document / update_document 的合并写语义:
        仅以传入字段覆盖现值, 其他进程刚写入的字段不受影响（行级天然隔离）。

        防覆盖: 已取消的文档, Worker 的进度/失败写回强制转为
        failed + 摘要"用户取消"（重试等显式重置传 bypass_guard=True 绕过）。

        :return: 合并后的文档; 不存在返回 None
        """
        fields = self.sanitize(fields)
        async with in_transaction():
            doc = await self.model.filter(job_id=job_id).select_for_update().first()
            if doc is None:
                return None
            if doc.status == self.DELETING_STATUS and not bypass_guard:
                # 删除流程已经接管该文档，旧解析 Worker 的迟到回写不得
                # 把 deleting 改回 parsing/embedding/complete 等状态。
                return doc
            if self._is_cancelled(doc) and not bypass_guard:
                fields = {**fields, "status": "failed", "summary": "用户取消"}
            doc.update_from_dict(fields)
            await doc.save()
            return doc

    async def cancel_active(self) -> Tuple[int, List[str]]:
        """把全部处理中文档标记为 failed + 用户取消（取消流程的数据库步骤）。

        :return: (标记数量, 对应 celery_task_id 列表)
        """
        async with in_transaction():
            docs = await self.model.filter(status__in=self.ACTIVE_STATUSES).select_for_update()
            if not docs:
                return 0, []
            job_ids = [d.job_id for d in docs]
            celery_task_ids = [d.celery_task_id for d in docs if d.celery_task_id]
            await self.model.filter(job_id__in=job_ids).update(
                status="failed", summary="用户取消", cancel_requested=True,
            )
            return len(job_ids), celery_task_ids

    # ==================== 巡检支撑 ====================

    async def list_stale_active_candidates(self, heartbeat_threshold: datetime) -> List[RagDocument]:
        """巡检候选: 中间态且心跳过期/缺失的文档（queued 不在此列, 按时长另行判定）。"""
        return await self.model.filter(
            Q(status__in=self.ACTIVE_PROCESSING_STATUSES)
            & (Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lt=heartbeat_threshold))
        ).all()

    async def list_stale_deleting_candidates(self, updated_threshold: datetime) -> List[RagDocument]:
        """查询长时间停留在 deleting 的文档，供删除任务补偿使用。"""
        return await self.model.filter(
            status=self.DELETING_STATUS,
            updated_time__lt=updated_threshold,
        ).all()

    async def mark_queued_failed(self, updated_before: datetime, summary: str) -> int:
        """滞留超容忍的 queued 文档直接标记失败（条件更新, 返回标记数）。"""
        return await self.model.filter(
            status="queued", updated_time__lte=updated_before,
        ).update(status="failed", summary=summary)

    async def mark_active_failed(
            self,
            job_id: str,
            expected_heartbeat: Optional[datetime],
            summary: str,
    ) -> bool:
        """巡检标记失败（乐观并发）: 仅当心跳仍停留在候选收集时刻的值才生效。

        查证 Celery 状态期间 Worker 若复活并刷新了心跳, heartbeat_at 已变化,
        条件更新命中 0 行即自动放弃标记, 避免误伤——等价于原实现的
        "写入前再看一眼心跳"。

        :return: 是否成功标记（False = 任务已复活或已离开中间态）
        """
        qs = self.model.filter(job_id=job_id, status__in=self.ACTIVE_PROCESSING_STATUSES)
        if expected_heartbeat is None:
            qs = qs.filter(heartbeat_at__isnull=True)
        else:
            qs = qs.filter(heartbeat_at=expected_heartbeat)
        updated = await qs.update(status="failed", summary=summary)
        return updated > 0

    # ==================== 删除 ====================

    async def fetch_and_remove(self, job_ids: List[str]) -> List[RagDocument]:
        """按 job_id 批量删除文档记录, 返回被删除的行（供磁盘/向量副作用清理）。"""
        if not job_ids:
            return []
        async with in_transaction():
            docs = await self.model.filter(job_id__in=job_ids).select_for_update()
            if docs:
                await self.model.filter(job_id__in=[d.job_id for d in docs]).delete()
        return list(docs)

    async def remove_if_deleting(self, job_id: str) -> bool:
        """仅在文档仍为 deleting 时物理删除 MySQL 记录。

        删除任务必须先完成外部资源清理，再调用此方法，避免向量或磁盘
        清理失败后文档记录已经丢失。条件删除也能防止其他流程误删记录。
        """
        if not job_id:
            return False
        deleted = await self.model.filter(
            job_id=job_id, status=self.DELETING_STATUS,
        ).delete()
        return deleted > 0

    async def set_deleting_task_id(self, job_id: str, task_id: str) -> bool:
        """记录 deleting 文档对应的 Celery 任务ID。

        仅允许仍处于 deleting 的文档写入，供后续任务状态查询、失败重试
        和超时补偿使用。
        """
        if not job_id or not task_id:
            return False
        updated = await self.model.filter(
            job_id=job_id, status=self.DELETING_STATUS,
        ).update(celery_task_id=task_id)
        return updated > 0

    async def record_deletion_failure(
            self,
            job_id: str,
            error_message: str,
            error_trace: Optional[str] = None,
            retryable: bool = True,
            error_type: Optional[str] = None,
    ) -> bool:
        """记录删除本次执行失败，并保存是否允许巡检补偿。

        这里不把文档改成 failed：failed 表示文档处理失败，而 deleting
        表示外部产物尚未清理完，改成 failed 会让残留文件/向量失去处理入口。
        ``retryable=False`` 时仍保留 deleting，但巡检不会再次投递，等待人工处理。
        """
        if not job_id:
            return False
        fields: Dict[str, Any] = {
            "summary": (
                f"删除暂时失败: {error_message}" if retryable
                else f"删除失败（不可自动补偿）: {error_message}"
            )[:1000],
            "deletion_retryable": retryable,
            "deletion_error_type": (error_type or "unknown")[:64],
        }
        if error_trace:
            fields["error_trace"] = error_trace[-5000:]
        updated = await self.model.filter(
            job_id=job_id, status=self.DELETING_STATUS,
        ).update(**fields)
        return updated > 0

    async def claim_deleting_recompensation(
            self,
            job_id: str,
            max_count: int,
    ) -> Optional[int]:
        """原子领取一次删除补偿名额，返回递增后的次数。

        使用行锁重新确认状态和次数，避免两个巡检实例同时给同一个
        job_id 重复投递。达到上限返回 None，且始终不改成 failed。
        """
        if not job_id or max_count <= 0:
            return None
        async with in_transaction():
            doc = await self.model.filter(
                job_id=job_id,
                status=self.DELETING_STATUS,
                deletion_retryable=True,
            ).select_for_update().first()
            if doc is None:
                return None
            current = int(doc.deleting_retry_count or 0)
            if current >= max_count:
                return None
            next_count = current + 1
            await self.model.filter(
                job_id=job_id, status=self.DELETING_STATUS,
            ).update(deleting_retry_count=next_count)
            return next_count
