"""开发者中心在线调试任务的创建、后台执行和查询服务。"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from applications.zhaoyunlong.models.online_debug_run_model import OnlineDebugRun as OnlineDebugRunModel

from .online_debug_service import OnlineDebugError, OnlineDebugService


class OnlineDebugRunNotFoundError(OnlineDebugError):
    """请求的在线调试任务不存在。"""


class OnlineDebugRunService:
    """使用进程内后台任务执行沙箱，并将运行状态写入数据库。"""

    _tasks: set[asyncio.Task[None]] = set()
    _MODEL_UNAVAILABLE_STATUS_CODES = frozenset({"429", "500", "504"})

    @classmethod
    async def create_and_start(
        cls,
        payload: dict[str, Any],
        owner_id: int,
        debugger: str,
    ) -> dict[str, Any]:
        """创建 queued 任务并立即调度后台沙箱执行。"""
        run_id = uuid.uuid4().hex
        record = await OnlineDebugRunModel.create(
            skill_id=str(payload["skill_id"]),
            run_id=run_id,
            status="queued",
            debugger=debugger[:64],
        )
        task = asyncio.create_task(
            cls._execute(record.id, run_id, payload, owner_id),
            name=f"online-debug-{run_id}",
        )
        cls._tasks.add(task)
        task.add_done_callback(cls._tasks.discard)
        return await cls.as_response(record)

    @classmethod
    async def _execute(
        cls,
        record_id: int,
        run_id: str,
        payload: dict[str, Any],
        owner_id: int,
    ) -> None:
        """在线程中执行阻塞的 Docker 调用，再回到事件循环更新任务状态。"""
        started_at = datetime.now()
        await OnlineDebugRunModel.filter(id=record_id).update(
            status="running",
            started_at=started_at,
            error_message=None,
        )
        try:
            sandbox = OnlineDebugService()
            result = await asyncio.to_thread(sandbox.run, payload, owner_id, run_id)
            finished_at = datetime.now()
            expires_at = finished_at + timedelta(seconds=sandbox.retention_seconds)
            await OnlineDebugRunModel.filter(id=record_id).update(
                status="completed",
                # 任务表只记录本次 run_id 目录；目录内的完整文件清单由 metadata.json 管理。
                result_file_path=str(result.result_dir),
                finished_at=finished_at,
                expires_at=expires_at,
                error_message=None,
            )
        except Exception as exc:
            finished_at = datetime.now()
            # 失败任务没有结果文件，也要在保留期后删除其错误记录。
            expires_at = finished_at + timedelta(seconds=OnlineDebugService().retention_seconds)
            await OnlineDebugRunModel.filter(id=record_id).update(
                status="failed",
                finished_at=finished_at,
                expires_at=expires_at,
                error_message=cls._get_public_error_message(exc),
            )

    @classmethod
    async def get_run(
        cls,
        run_id: str,
    ) -> OnlineDebugRunModel:
        """按任务编号读取任务。"""
        record = await OnlineDebugRunModel.filter(run_id=run_id).first()
        if record is None:
            raise OnlineDebugRunNotFoundError("在线调试任务不存在")
        return record

    @classmethod
    async def get_latest_run(
        cls,
        skill_id: str,
    ) -> OnlineDebugRunModel:
        """读取某个技能最近创建的一次调试任务。"""
        query = OnlineDebugRunModel.filter(skill_id=skill_id)
        record = await query.order_by("-id").first()
        if record is None:
            raise OnlineDebugRunNotFoundError("该技能暂无在线调试任务")
        return record

    @classmethod
    async def get_document_path(
        cls,
        run_id: str,
        owner_id: int,
        is_superuser: bool,
        filename: str | None = None,
    ) -> tuple[Path, str, str]:
        """校验任务状态、权限和有效期后返回指定结果文件路径。"""
        record = await cls.get_run(run_id)
        if record.status != "completed":
            raise OnlineDebugError("调试任务尚未完成，暂不能下载结果文档")
        # 使用与数据库过期时间一致的时区，兼容带时区及不带时区的时间。
        if record.expires_at is not None and record.expires_at <= datetime.now(record.expires_at.tzinfo):
            raise OnlineDebugError("调试结果文档已过期，请重新运行调试")
        if not record.result_file_path:
            raise OnlineDebugError("调试任务未保存结果目录信息")

        # 任务表只存运行目录；真正下载时仍使用元数据校验文件归属和文件名。
        document = await asyncio.to_thread(
            OnlineDebugService().get_document,
            run_id,
            owner_id,
            is_superuser,
            filename,
        )
        return document.file_path, document.filename, document.media_type

    @classmethod
    async def as_response(cls, record: OnlineDebugRunModel) -> dict[str, Any]:
        """将任务记录转换为前端可直接展示的安全响应，不泄露服务端文件路径。"""
        response: dict[str, Any] = {
            "run_id": record.run_id,
            "skill_id": record.skill_id,
            "debugger": record.debugger,
            "status": record.status,
            "started_at": cls._format_datetime(record.started_at),
            "finished_at": cls._format_datetime(record.finished_at),
            "error_message": record.error_message if record.status == "failed" else None,
        }
        if record.status == "completed":
            expires_at = cls._format_datetime(record.expires_at)
            # 文件清单以结果目录 metadata.json 为准；单个结果同样以长度为 1 的数组返回。
            try:
                documents = await asyncio.to_thread(
                    OnlineDebugService().get_documents,
                    record.run_id,
                    0,
                    True,
                )
                response["documents"] = [
                    document.as_response(record.run_id, expires_at or "") for document in documents
                ]
            except OnlineDebugError:
                response["documents"] = []
        return response

    @staticmethod
    def _format_datetime(value: datetime | None) -> str | None:
        """将数据库时间转换为 ISO 8601 字符串，空值保持为空。"""
        return value.isoformat() if value is not None else None

    @classmethod
    def _get_public_error_message(cls, exc: Exception) -> str:
        """将模型服务的临时不可用错误转换为前端统一提示。"""
        detail = str(exc).strip()
        # 仅处理 Claude Agent SDK 回传的模型服务状态，避免把普通业务文本中的数字误判为 HTTP 状态码。
        if "Claude Agent SDK" in detail:
            status_codes = set(re.findall(r"(?<!\d)(429|500|504)(?!\d)", detail))
            if status_codes & cls._MODEL_UNAVAILABLE_STATUS_CODES:
                return "模型不可用，请稍后再试"
        return detail[:2000] or "在线调试执行失败"
