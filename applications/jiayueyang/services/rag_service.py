# -*- coding: utf-8 -*-
"""RAG 文档状态管理服务。

MySQL（keenrobot_rag_document 表）作为文档状态的跨进程唯一数据源:
Web 进程与 Celery Worker 进程均经 Tortoise ORM 读写, 行级更新 + 事务内
SELECT FOR UPDATE + 条件更新天然防丢更新; JSON 时代的"portalocker 文件锁 +
全量读-改-写"已退役。流水线运行状态与历史消息同样持久化于 MySQL
（rag_pipeline_state / rag_pipeline_history, 见 pipeline_crud.py）,
rag_storage 文件存储已整体下线。

对外方法统一以 dict 快照（字段名与旧 JSON 记录一致, id=job_id）收发,
流水线与视图无需感知 ORM; 快照由 model_to_dict 生成。
"""
import asyncio
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from applications.jiayueyang.models.rag_document_model import RagDocument
from applications.jiayueyang.services.pipeline_crud import PipelineCrud
from applications.jiayueyang.services.rag_document_crud import RagDocumentCrud
from configure import LOGGER, PROJECT_CONFIG

_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _fmt_time(value: Optional[datetime]) -> str:
    """datetime → 'yyyy-MM-dd HH:mm:ss'; 空值为 ''（前端契约不变）。"""
    return value.strftime(_TIME_FMT) if value else ""


class RagDocumentService:
    """文档状态管理服务（MySQL 存储, 跨进程安全）。

    说明: Web 端以单例方式使用（见 applications.jiayueyang.dependencies）;
    Celery 异步任务内可按需实例化（任务体运行于常驻事件循环线程,
    见 celery_scheduler.celery_base, 直接 await ORM 操作）。
    """

    # 处理中状态集合（状态机中间态）; queued = 条目已建但 Celery 尚未确认派发
    ACTIVE_STATUSES = RagDocumentCrud.ACTIVE_STATUSES

    # 心跳超时容忍: 超过该时长未刷新心跳, 视为 Worker 已失联
    STALE_HEARTBEAT_SECONDS = 15 * 60
    # queued 文档滞留超过该时长仍未派发, 视为任务丢失
    STALE_QUEUED_SECONDS = 10 * 60

    def __init__(self):
        self.crud = RagDocumentCrud()
        # 流水线状态/历史 CRUD（MySQL, 跨进程共享）
        self.pipeline = PipelineCrud()

    # ==================== 模型 <-> dict 快照 ====================

    @staticmethod
    def model_to_dict(doc: RagDocument) -> Dict[str, Any]:
        """模型实例 → 流水线惯用 dict 快照（字段名与旧 JSON 记录一致）。

        说明: id 即 job_id; created_at/updated_at 由 TimestampMixin 自动维护;
        markdown 从不落库（按产物文件读取, 见 _read_markdown）。
        """
        return {
            "id": doc.job_id,
            "filename": doc.filename,
            "status": doc.status,
            "summary": doc.summary,
            "input_path": doc.input_path or "",
            "output_path": doc.output_path or "",
            "artifacts_file": doc.artifacts_file or "",
            "sidecar": doc.sidecar or {},
            "chunks_file": doc.chunks_file or "",
            "do_ocr": doc.do_ocr,
            "force_ocr": doc.force_ocr,
            "enable_vlm": doc.enable_vlm,
            "chunk_strategy": doc.chunk_strategy,
            "page_count": doc.page_count,
            "total_parts": doc.total_parts,
            "completed_parts": doc.completed_parts,
            "terminology_total_batches": doc.terminology_total_batches,
            "terminology_completed_batches": doc.terminology_completed_batches,
            "analyzing_stage_skipped": doc.analyzing_stage_skipped,
            "celery_task_id": doc.celery_task_id,
            "heartbeat_at": _fmt_time(doc.heartbeat_at),
            "cancel_requested": doc.cancel_requested,
            "resume": doc.resume,
            "content_length": doc.content_length,
            "chunks_count": doc.chunks_count,
            "error_trace": doc.error_trace or "",
            "file_sha256": doc.file_sha256 or "",
            "is_updating": doc.is_updating,
            "update_history": doc.update_history or [],
            "parse_start_time": _fmt_time(doc.parse_start_time),
            "parse_end_time": _fmt_time(doc.parse_end_time),
            "parse_duration": doc.parse_duration,
            "term_start_time": _fmt_time(doc.term_start_time),
            "term_end_time": _fmt_time(doc.term_end_time),
            "analyze_start_time": _fmt_time(doc.analyze_start_time),
            "analyze_end_time": _fmt_time(doc.analyze_end_time),
            "analyze_duration": doc.analyze_duration,
            "chunk_start_time": _fmt_time(doc.chunk_start_time),
            "chunk_end_time": _fmt_time(doc.chunk_end_time),
            "embed_start_time": _fmt_time(doc.embed_start_time),
            "embed_end_time": _fmt_time(doc.embed_end_time),
            "process_end_time": _fmt_time(doc.process_end_time),
            "created_at": _fmt_time(doc.created_time),
            "updated_at": _fmt_time(doc.updated_time),
        }

    # ==================== 读写方法（异步）====================

    async def load_all(self) -> Dict[str, Dict[str, Any]]:
        """即时加载全部文档状态（job_id → dict 快照, 每次查库最新数据）。"""
        docs = await self.crud.list_all()
        return {d.job_id: self.model_to_dict(d) for d in docs}

    async def get_document_entry(self, job_id: str) -> Optional[Dict[str, Any]]:
        """按 job_id 获取单个文档的 dict 快照; 不存在返回 None。"""
        doc = await self.crud.get_by_job_id(job_id)
        return self.model_to_dict(doc) if doc else None

    async def save_document(self, doc: Dict[str, Any], bypass_guard: bool = False) -> Dict[str, Any]:
        """单文档归并保存（行级合并, 仅覆盖传入字段）。

        防覆盖: 若库中文档已被标记为"用户取消", 则 Worker 的进度/失败
        写回不得将其复活或篡改摘要（重试等显式状态重置可传 bypass_guard=True 绕过）。

        :return: 实际持久化的文档快照（合并后的最新形态）
        """
        fields = {**doc}
        job_id = fields.pop("id", None) or doc.get("id")
        merged = await self.crud.merge_update(job_id, fields, bypass_guard=bypass_guard)
        if merged is None:
            # 与原 JSON 语义对齐的兜底: 文档已被删除时以传入快照回应调用方
            return doc
        return self.model_to_dict(merged)

    async def update_document(self, job_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """字段级局部更新: 仅合并传入字段, 返回合并后的快照。

        流水线中"只改几个字段"的场景（回写 celery_task_id、子文档进度等）
        统一走这里, 避免以过期整份快照覆盖其他进程的写入。防覆盖守卫同样
        生效: 用户取消的文档不得被进度写回复活。

        :return: 合并后的文档快照; 文档不存在时返回 None
        """
        merged = await self.crud.merge_update(job_id, fields)
        return self.model_to_dict(merged) if merged else None

    async def create_document(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """原子创建文档条目: 重名查重（大小写不敏感）+ 唯一约束兜底。

        :raises DataAlreadyExistsException: 已存在同名文档（忽略大小写）
        """
        doc = await self.crud.create_document(entry)
        return self.model_to_dict(doc)

    # ==================== 僵尸任务巡检 ====================

    async def sweep_stale_documents(self) -> int:
        """巡检并标记确定性死亡的任务为 failed（Web 启动与周期任务调用）。

        判定只依据"任务已死"的肯定证据, 避免 Web 单独重启时误伤:
        - queued 滞留超容忍（派发丢失, 见提交流程的失败分支）;
        - 中间态且心跳过期/缺失, 同时 Celery 侧任务处于终态
          （FAILURE/REVOKED）或确认失联（PENDING 且超容忍）;
        - 心跳新鲜或 Celery 侧仍 STARTED 的任务一律跳过。

        标记采用条件更新（乐观并发）: 仅当心跳仍停留在候选收集时刻的值
        才生效, 查证期间 Worker 复活即自动放弃, 无需全局锁。

        :return: 本次标记为失败的文档数
        """
        now_dt = datetime.now()
        hb_threshold = now_dt - timedelta(seconds=self.STALE_HEARTBEAT_SECONDS)

        # 阶段1: 收集候选（中间态且心跳过期/缺失, 不含 queued; 无网络 IO）
        candidates = await self.crud.list_stale_active_candidates(hb_threshold)

        # 阶段2: 逐个复核 Celery 任务状态（同步 Redis 查询移交线程池, 不阻塞事件循环）
        verdicts: Dict[str, bool] = {}
        for doc in candidates:
            state = await asyncio.to_thread(self._celery_task_state, doc.celery_task_id)
            if state in ("STARTED", "RETRY"):
                verdicts[doc.job_id] = False  # 任务仍在运行（心跳可能只是暂未及时刷新）
            elif state == "PENDING":
                # 排队中, 或结果已过期（result_expires）导致状态未知:
                # 仅当心跳/创建时间超容忍才判定失联
                age_ref = doc.heartbeat_at or doc.created_time
                age = (now_dt - age_ref).total_seconds() if age_ref else None
                verdicts[doc.job_id] = age is not None and age > self.STALE_HEARTBEAT_SECONDS
            else:
                # FAILURE / REVOKED / None（无此任务）→ 确认失联
                verdicts[doc.job_id] = True

        # 阶段3: 复核后标记失败（条件更新: 心跳已刷新则自动放弃, 防误伤复活任务）
        marked = 0
        for doc in candidates:
            if not verdicts.get(doc.job_id):
                continue
            if await self.crud.mark_active_failed(
                doc.job_id, doc.heartbeat_at, "任务中断（工作进程失联）, 请重试",
            ):
                marked += 1

        # queued 滞留: 按时长直接判定（updated_time 由 auto_now 维护）
        queued_before = now_dt - timedelta(seconds=self.STALE_QUEUED_SECONDS)
        marked += await self.crud.mark_queued_failed(queued_before, "任务派发后失联, 请重试")

        if marked:
            LOGGER.warning(f"僵尸任务巡检: 标记 {marked} 个失联任务为失败")
        return marked

    @staticmethod
    def _celery_task_state(task_id: Optional[str]) -> Optional[str]:
        """查询 Celery 任务状态（PENDING/STARTED/FAILURE/REVOKED 等）, 失败返回 None。

        依赖 result_backend 与 task_track_started=True; 结果过期
        （result_expires=3600）后状态回落为 PENDING, 调用方需结合心跳账龄判定。
        """
        if not task_id:
            return None
        try:
            from celery.result import AsyncResult
            from celery_scheduler.celery_worker import celery
            return AsyncResult(task_id, app=celery).state
        except Exception as e:
            LOGGER.warning(f"查询 Celery 任务状态失败: {task_id}, {e}")
            return None

    # ==================== 内部工具 ====================

    @staticmethod
    def make_doc_entry(job_id: str, filename: str, input_path: str) -> Dict[str, Any]:
        """构造一个新的文档状态条目（字段为模型可写键; 时间由数据库自动维护）。"""
        return {
            "job_id": job_id, "filename": filename, "status": "parsing",
            "summary": "-", "content_length": None,
            "chunks_count": None, "input_path": input_path, "output_path": "",
        }

    @staticmethod
    def now_time() -> str:
        """当前时间字符串（yyyy-MM-dd HH:mm:ss）。"""
        import time
        return time.strftime("%Y-%m-%d %H:%M:%S")

    async def add_history(self, message: str) -> None:
        """追加一条流水线历史消息（持久化于 MySQL, 跨进程共享）。"""
        await self.pipeline.append_history(message)

    @staticmethod
    def _rollback_available(d: Dict[str, Any]) -> bool:
        """失败文档是否可回滚: prev 归档齐备（产物目录 + 字段快照 + 向量产物）。

        prev 归档由增量更新的归档事务生成（RAG_OUTPUT_DIR/<job_id>.prev/）;
        三要素缺一即不可回滚: 缺快照无法恢复文档字段, 缺 embeddings.json
        无法重写向量库。目录探测为本地 stat, 列表/轮询路径开销可忽略。
        """
        if d.get("status") != "failed":
            return False
        prev_dir = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR) / f"{d['id']}.prev"
        return (
            prev_dir.is_dir()
            and (prev_dir / "doc_snapshot.json").is_file()
            and (prev_dir / "embeddings.json").is_file()
        )

    @staticmethod
    def to_response(d: Dict[str, Any]) -> Dict[str, Any]:
        """文档 dict 快照转接口响应格式（34 字段, 新增增量更新相关 4 字段）。"""
        return {
            "id": d["id"], "filename": d["filename"], "status": d["status"],
            "summary": d.get("summary", "-"), "content_length": d.get("content_length"),
            "chunks_count": d.get("chunks_count"),
            "total_parts": d.get("total_parts", 1),
            "completed_parts": d.get("completed_parts", 0),
            "terminology_total_batches": d.get("terminology_total_batches", 1),
            "terminology_completed_batches": d.get("terminology_completed_batches", 0),
            # 服务器绝对路径一律不对外暴露（防内部信息泄露）: 保留字段、置空值;
            # 产物清理由服务端按 job_id 自行推导路径, 前端无需也拿不到真实路径
            "chunks_file": "",
            "input_path": "",
            "created_at": d.get("created_at", ""),
            "updated_at": d.get("updated_at", ""),
            "parse_start_time": d.get("parse_start_time", ""),
            "parse_end_time": d.get("parse_end_time", ""),
            "parse_duration": d.get("parse_duration"),
            "term_start_time": d.get("term_start_time", ""),
            "term_end_time": d.get("term_end_time", ""),
            "analyze_start_time": d.get("analyze_start_time", ""),
            "analyze_end_time": d.get("analyze_end_time", ""),
            "analyzing_stage_skipped": d.get("analyzing_stage_skipped", False),
            "chunk_start_time": d.get("chunk_start_time", ""),
            "chunk_end_time": d.get("chunk_end_time", ""),
            "embed_start_time": d.get("embed_start_time", ""),
            "embed_end_time": d.get("embed_end_time", ""),
            "process_end_time": d.get("process_end_time", ""),
            "page_count": d.get("page_count"),
            "error_msg": d.get("summary", "") if d.get("status") == "failed" else "",
            "error_trace": d.get("error_trace", ""),
            # ---- 增量更新相关（新增字段, 旧前端忽略不影响既有功能） ----
            "file_sha256": d.get("file_sha256", ""),
            "is_updating": d.get("is_updating", False),
            "update_history": d.get("update_history") or [],
            "rollback_available": RagDocumentService._rollback_available(d),
        }

    # ==================== 查询方法 ====================

    async def get_all_documents(self) -> List[Dict[str, Any]]:
        """获取全部文档（按创建时间倒序）。"""
        docs = await self.crud.list_all()
        return [self.to_response(self.model_to_dict(d)) for d in docs]

    async def get_document(self, job_id: str) -> Optional[Dict[str, Any]]:
        """按 job_id 获取单个文档详情（状态轮询用, 不含 markdown 全文）。"""
        entry = await self.get_document_entry(job_id)
        if not entry:
            return None
        return self.to_response(entry)

    async def get_document_markdown(self, job_id: str) -> Optional[str]:
        """按 job_id 获取文档解析产物的 markdown 全文; 文档不存在返回 None。

        markdown 不做持久化, 从产物目录的 md 文件读取（不存在时为空串）。
        """
        entry = await self.get_document_entry(job_id)
        if not entry:
            return None
        return self._read_markdown(entry)

    async def get_document_terminology(self, job_id: str) -> Optional[str]:
        """按 job_id 获取术语对照表 markdown 全文; 文档不存在返回 None。

        术语表产物 terminology.md 与文档 md 同在解析产物目录, 不落库,
        按需读取（不存在时为空串: 术语提取失败或跳过时不生成）。
        """
        entry = await self.get_document_entry(job_id)
        if not entry:
            return None
        return self._read_terminology(entry)

    async def get_document_chunks(self, job_id: str) -> Optional[List[Dict[str, Any]]]:
        """按 job_id 获取最终入库的分块列表; 文档不存在返回 None。

        读取分块产物 chunks.json——流水线保证其与 embeddings.json、向量库
        三者口径一致（空块过滤后同一份数据落盘/嵌入/入库）, 无需查询向量库。
        产物不存在（未完成分块/已清理）时返回空列表。
        """
        entry = await self.get_document_entry(job_id)
        if not entry:
            return None
        chunks_file = entry.get("chunks_file") or ""
        if not chunks_file:
            return []
        path = Path(chunks_file)
        try:
            if not path.is_file():
                return []
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            LOGGER.warning(f"读取分块产物失败: {chunks_file}, {e}")
            return []
        chunks: List[Dict[str, Any]] = []
        for key, c in raw.items():
            c = c or {}
            chunks.append({
                "id": key,
                "order": c.get("chunk_order_index", 0),
                "modality": c.get("modality") or "text",
                "tokens": c.get("tokens", 0),
                "content": c.get("content", ""),
            })
        chunks.sort(key=lambda item: item["order"])
        return chunks

    @staticmethod
    def _read_markdown(doc: Dict[str, Any]) -> str:
        """从产物目录读取文档 markdown 全文（不存在时返回空串; markdown 不落库）。"""
        output_path = doc.get("output_path") or ""
        filename = doc.get("filename") or ""
        if not output_path or not filename:
            return ""
        md_path = Path(output_path) / f"{Path(filename).stem}.md"
        try:
            if md_path.exists():
                return md_path.read_text(encoding="utf-8")
        except OSError as e:
            LOGGER.warning(f"读取 markdown 失败: {md_path}, {e}")
        return ""

    @staticmethod
    def _read_terminology(doc: Dict[str, Any]) -> str:
        """从产物目录读取术语对照表 terminology.md（不存在时返回空串; 不落库）。"""
        output_path = doc.get("output_path") or ""
        if not output_path:
            return ""
        term_path = Path(output_path) / "terminology.md"
        try:
            if term_path.exists():
                return term_path.read_text(encoding="utf-8")
        except OSError as e:
            LOGGER.warning(f"读取术语表失败: {term_path}, {e}")
        return ""

    async def get_pipeline_status(self) -> Dict[str, Any]:
        """获取流水线整体运行状态（文档状态 / 流水线状态 / 历史均查 MySQL）。"""
        docs = await self.crud.list_all()
        start_dt = await self.pipeline.get_start_time()
        history: List[str] = await self.pipeline.read_history()

        active_docs = [d for d in docs if d.status in self.ACTIVE_STATUSES]
        busy = bool(active_docs)
        job_name = ", ".join(d.filename for d in active_docs) or "-"
        total = len(docs)

        # 自愈: 无处理中文档却残留启动时间（进程被杀未走 finally 清理）, 就地清空
        if not busy and start_dt:
            start_dt = None
            await self.pipeline.set_start_time(None)

        # 仅统计处理中的文档（排除已完成的）
        part_total = sum(d.total_parts for d in active_docs)
        part_done = sum(d.completed_parts for d in active_docs)

        return {
            "busy": busy,
            "job_name": job_name,
            "job_start": _fmt_time(start_dt),
            "docs": total,
            "batchs": total if busy else 0,
            "cur_batch": len(active_docs) if busy else 0,
            "part_total": part_total if busy else 0,
            "part_done": part_done if busy else 0,
            "request_pending": False,
            # 取消在 Celery 模式下即时生效（文档直接标记失败）, 不存在中间请求态
            "cancellation_requested": False,
            "latest_message": history[-1] if history else "-",
            "history_messages": list(history),
        }

    # ==================== 操作方法 ====================

    async def cancel_all_tasks(self, force: bool = False) -> Dict[str, Any]:
        """取消全部处理中的任务。

        将处理中的文档直接标记为失败（用户取消）;
        Worker 进程在各阶段检查点检测到状态变化后自行停止。

        :param force: True = 额外杀掉运行中的 worker 子进程使取消立即生效
            （docling 单子文档转换不可打断, 软取消需等当前子文档结束）
        """
        cancelled, celery_task_ids = await self.crud.cancel_active()

        # 清流水线启动时间（MySQL 行级更新, 原子）
        await self.pipeline.set_start_time(None)

        # 撤销尚在队列中未开始的 Celery 任务（网络 IO 不阻塞事件循环; 运行中的
        # 任务由检查点机制停止）; force 时额外 terminate 杀掉运行中的 worker
        # 子进程——acks_late 下消息会重回队列, 但文档已被标记取消, 重投递任务
        # 检测到 cancel_requested 后立即退出
        await asyncio.to_thread(self._revoke_celery_tasks, celery_task_ids, force)

        msg = f"已取消 {cancelled} 个任务"
        await self.add_history(msg)
        LOGGER.info(f"取消任务: {msg}")
        return {"status": "cancellation_requested" if cancelled > 0 else "not_busy", "message": msg}

    @staticmethod
    def _revoke_celery_tasks(celery_task_ids: List[str], terminate: bool = False) -> None:
        """撤销指定的 Celery 任务（broker 不可用时仅告警）。

        :param terminate: 是否同时杀掉运行中的 worker 子进程（强制取消）
        """
        if not celery_task_ids:
            return
        try:
            from celery_scheduler.celery_worker import celery
            for task_id in celery_task_ids:
                celery.control.revoke(task_id, terminate=terminate, signal="SIGTERM")
        except Exception as e:
            LOGGER.warning(f"撤销 Celery 任务失败（不影响取消生效）: {e}")

    async def delete_files_and_docs(self, job_ids: str) -> Dict[str, Any]:
        """移除文档条目并清理其全部关联产物。

        :param job_ids: 换行分隔的待移除文档 job_id
        :return: 删除结果（deleted/failed 两个 job_id 列表）

        磁盘路径（源文件留档目录 / 解析产物目录）完全由服务端文档记录推导,
        不接受客户端传入路径——避免服务器绝对路径外泄及任意路径删除风险。
        """
        ids = [j.strip() for j in job_ids.strip().split("\n") if j.strip()]
        removed_docs = await self.crud.fetch_and_remove(ids)
        removed_job_ids = [d.job_id for d in removed_docs]

        # 副作用（文件删除 / Milvus 向量删除）为同步阻塞 IO, 移交线程池执行。
        snapshots = [self.model_to_dict(d) for d in removed_docs]
        await asyncio.to_thread(self._cleanup_artifacts, snapshots)
        return {"deleted": removed_job_ids, "failed": []}

    def _cleanup_artifacts(self, docs: List[Dict[str, Any]]) -> None:
        """删除文档的磁盘产物与向量库条目（线程池内执行, 尽力而为）。"""
        for doc in docs:
            self._remove_input_dir(doc)
            self._remove_output_dirs(doc)
        for doc in docs:
            self._delete_vectors(doc["id"])

    @staticmethod
    def _remove_input_dir(doc: Dict[str, Any]) -> None:
        """清理文档的源文件留档目录（input/<job_id>/ 及增量更新 prev 归档, 尽力而为）。"""
        targets: List[Path] = []
        input_path = doc.get("input_path") or ""
        if input_path:
            targets.append(Path(input_path).parent)
        job_id = doc.get("id") or ""
        if job_id:
            # 更新失败时上一版本的源文件留档在 <job_id>.prev, 一并回收
            targets.append(Path(PROJECT_CONFIG.RAG_INPUT_DIR) / f"{job_id}.prev")
        for input_dir in targets:
            try:
                if input_dir.is_dir():
                    shutil.rmtree(input_dir)
            except Exception as e:
                LOGGER.warning(f"清理源文件留档目录失败（{input_dir}）: {e}")

    @staticmethod
    def _resume_artifacts_ready(doc: Dict[str, Any]) -> bool:
        """失败文档的解析产物是否完整（续跑前提, 重试侧与执行侧共用判据）。

        三项齐备说明"解析 + 侧车"阶段已完成, 后处理管道（术语 → 多模态
        → 分块 → 嵌入）可从首个未完成的阶段续跑:
        1. 产物目录存在（output_path）;
        2. 清洗后的 markdown 已落盘（<stem>.md）;
        3. 侧车已写入文档记录（sidecar 非空, 分块阶段依赖其 blocks/tables）。
        任一缺失 → 不可续跑, 回退全量重跑。
        """
        output_path = doc.get("output_path") or ""
        if not output_path or not (doc.get("sidecar") or {}):
            return False
        bundle_dir = Path(output_path)
        stem = Path(doc.get("filename") or "").stem
        if not stem or not bundle_dir.is_dir():
            return False
        return (bundle_dir / f"{stem}.md").is_file()

    @staticmethod
    def _remove_output_dirs(doc: Dict[str, Any]) -> None:
        """清理文档在输出目录下的解析产物（尽力而为, 失败仅告警）。

        两部分:
        1. 主产物目录（output_path, 形如 RAG_OUTPUT_DIR/<job_id>）——前端
           清除对话框也会通过 paths 参数传递它, 此处按文档记录兜底再删一次,
           保证即使前端未传也能回收; 仅当路径确实位于 RAG_OUTPUT_DIR 内
           才删除（防御旧记录中的异常值）;
        2. 分片流程的子文档目录（RAG_OUTPUT_DIR/<job_id>_part_*）——前端
           无从得知这些路径, 任务在合并前被取消/中断（如 Worker 被强杀,
           连流水线自身的 finally 清理都没来得及执行）时它们会残留, 只能
           由服务侧按 job_id 统一回收。
        """
        base = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR)

        output_path = doc.get("output_path") or ""
        if output_path:
            try:
                out_dir = Path(output_path)
                if out_dir.is_dir() and out_dir.resolve().is_relative_to(base.resolve()):
                    shutil.rmtree(out_dir, ignore_errors=True)
            except Exception as e:
                LOGGER.warning(f"清理主产物目录失败（{output_path}）: {e}")

        job_id = doc.get("id") or ""
        if not job_id:
            return
        try:
            for part_dir in base.glob(f"{job_id}_part_*"):
                if part_dir.is_dir():
                    shutil.rmtree(part_dir, ignore_errors=True)
        except Exception as e:
            LOGGER.warning(f"清理子文档产物目录失败（{job_id}）: {e}")

        # 增量更新 prev 归档（更新失败时上一版本产物留在 <job_id>.prev）
        try:
            prev_dir = base / f"{job_id}.prev"
            if prev_dir.is_dir():
                shutil.rmtree(prev_dir, ignore_errors=True)
        except Exception as e:
            LOGGER.warning(f"清理 prev 归档失败（{job_id}）: {e}")

    @staticmethod
    def _delete_vectors(doc_id: str) -> None:
        """删除向量库中指定文档的全部分块（尽力而为, 失败仅告警）。"""
        try:
            from applications.jiayueyang.rag.milvus_store import delete_by_doc_id
            delete_by_doc_id(doc_id)
        except Exception as e:
            LOGGER.warning(f"删除文档向量失败（{doc_id}）: {e}")
