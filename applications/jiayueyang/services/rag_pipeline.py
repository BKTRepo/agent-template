# -*- coding: utf-8 -*-
"""RAG 文档处理后台流水线服务。

包含三条流水线:
1. 单文档流程: 原生 docling 离线解析 → 侧车文件 → 后处理(术语/多模态/分块/嵌入)
2. 分片文档批量流程: 大 PDF 分片 → convert_all 共享流水线解析 → 按序合并 → 后处理
3. 共享后处理管道: 术语抽取 → 多模态分析 → 分块 → 向量嵌入

Web 端通过 Celery 分发任务（submit_conversion）, 所有耗时操作均在 Worker 进程执行;
文档状态全程经 RagDocumentService 写回 MySQL（keenrobot_rag_document 表, 跨进程共享）。
"""
import asyncio
import hashlib
import json
import math
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from applications.jiayueyang.services.rag_service import RagDocumentService
from common.docling_native import (
    ConversionCancelledError,
    convert_pdf_to_bundle,
    convert_pdfs_to_bundles,
)
from common.file_utils import sanitize_upload_filename
from common.pdf_utils import get_pdf_page_count, split_pdf
from configure import CELERY_CONFIG, LOGGER, PROJECT_CONFIG
from core.exceptions import (
    NotFoundException,
    ParameterException,
)

# Celery 任务注册名
PROCESS_DOCUMENT_TASK = "celery_scheduler.tasks.task_rag_pipeline.process_document_task"
ROLLBACK_DOCUMENT_TASK = "celery_scheduler.tasks.task_rag_pipeline.rollback_document_task"

# 增量更新 prev 归档目录后缀: output/rag_upload/<job_id>.prev 与 input/<job_id>.prev
PREV_SUFFIX = ".prev"


def _now_iso() -> str:
    """返回带本地时区的日志时间戳，便于和接口/LLM日志直接对照。"""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")

# 重复任务防护: 本进程内正在执行的 job_id 集合（+创建锁）。
# 背景: task_acks_late 下 worker 崩溃时消息未确认, 重启后 Redis 会重投递,
# 若用户同时又重新提交, 同一 job_id 会被两个任务并行执行、互相覆盖文档状态。
# 命中已在执行的 job_id 时, 后到的任务立即返回失败（消息随之正常 ack, 不再复活）。
_ACTIVE_JOB_IDS: set = set()
_ACTIVE_JOB_LOCK = threading.Lock()

# 跨进程任务执行锁（Redis, 复用 Celery broker 连接）。
# 背景: 进程内 _ACTIVE_JOB_IDS 只能防同一进程内的重复执行; 而 task_acks_late +
# task_reject_on_worker_lost 下, worker 崩溃后消息重投递可能落到**另一个** worker
# 进程, 进程内集合拦不住, 仍会双任务并行覆盖同一文档。Redis 锁是跨进程权威防线。
_JOB_LOCK_PREFIX = "rag:job-lock:"
_JOB_LOCK_TTL_MS = 3_700_000  # 略大于 time_limit=3600s; 崩溃后锁自然过期, 心跳写回时续期
_REDIS_CLIENT = None

# Lua 检查并删除: 仅当锁仍属于自己（token 一致）时才释放, 防误删他人之锁
_RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


def _redis_client():
    """惰性构建 Redis 客户端（复用 Celery broker 连接配置）。"""
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        import redis
        _REDIS_CLIENT = redis.Redis.from_url(CELERY_CONFIG.CELERY_BROKER_URL)
    return _REDIS_CLIENT


def _acquire_job_lock(job_id: str, token: str) -> bool:
    """获取跨进程任务执行锁; 同 token 可重入（acks_late 重投递的任务 task_id 不变, 允许接管续跑）。

    Redis 不可用时失败放行（降级回进程内 _ACTIVE_JOB_IDS 防护）, 可用性优先。
    """
    try:
        r = _redis_client()
        key = _JOB_LOCK_PREFIX + job_id
        if r.set(key, token, nx=True, px=_JOB_LOCK_TTL_MS):
            return True
        held = r.get(key)
        return held is not None and held.decode() == token
    except Exception as e:
        LOGGER.warning(f"任务锁不可用, 降级放行: job_id={job_id}, {e}")
        return True


def _acquire_delete_job_lock(job_id: str, token: str) -> bool:
    """删除流程专用的严格加锁。

    与解析/写入流程使用同一个 ``job_id`` 锁 key，保证两类操作互斥；
    但删除属于不可逆操作，Redis 不可用时禁止降级放行，直接抛出异常，
    由删除任务的重试策略决定后续处理。
    """
    r = _redis_client()
    key = _JOB_LOCK_PREFIX + job_id
    if r.set(key, token, nx=True, px=_JOB_LOCK_TTL_MS):
        return True
    held = r.get(key)
    return held is not None and held.decode() == token


def _refresh_job_lock(job_id: str, token: str) -> None:
    """续期锁有效期（Worker 心跳写回时调用, 防长任务锁过期后被误抢占）。"""
    try:
        r = _redis_client()
        key = _JOB_LOCK_PREFIX + job_id
        held = r.get(key)
        if held is not None and held.decode() == token:
            r.pexpire(key, _JOB_LOCK_TTL_MS)
    except Exception:
        pass  # 尽力续期; 失败最坏后果是锁自然过期, 不影响数据正确性


def _release_job_lock(job_id: str, token: str) -> None:
    """释放锁（Lua 检查并删除, 防误删其他执行者持有的锁）。"""
    _release_job_lock_if_owner(job_id, token)


def _release_job_lock_if_owner(job_id: str, token: str) -> bool:
    """仅当锁仍属于指定 token 时释放，并返回是否实际释放。

    巡检确认 Worker 已失联后会调用此方法清理遗留锁。Lua 脚本会在
    Redis 内原子地比较 value 和 token，避免误删后来获得同一 job_id 锁的
    新任务。
    """
    try:
        result = _redis_client().eval(
            _RELEASE_LOCK_LUA, 1, _JOB_LOCK_PREFIX + job_id, token,
        )
        return bool(result)
    except Exception as e:
        LOGGER.warning(f"任务锁释放失败（将等待自然过期）: job_id={job_id}, {e}")
        return False


class RagPipelineService:
    """文档处理后台流水线服务（依赖文档状态管理服务）。"""

    def __init__(self, document_service: RagDocumentService):
        self.document_service = document_service
        # 当前任务执行 token（Celery task id）: 分布式锁重入与释放凭证。
        # Web 端恒为 None（Web 不执行流水线, 不打心跳）; Worker 端每个任务
        # 独立实例化本服务（见 task_rag_pipeline）, 由 process_document 入口赋值
        self._execution_token: Optional[str] = None
        # 取消内存标记（job_id -> 是否已取消）: 同步检查点（docling 回调运行在
        # 工作线程）无法跨线程查询 MySQL, 只读内存; 标记由 _save/_update（心跳
        # 写回）与 refresh_cancel_state（异步检查点）维护, 分片等待侧另有 5 秒
        # 周期刷新（见 _consume_progress）, 时效性与原 JSON 直读方案一致
        self._cancel_flags: Dict[str, bool] = {}
        # 快速通道②命中登记（job_id -> 复用的向量数）: 解析产物逐字节一致时
        # embeddings.json 整体复制回, 阶段 4 走"向量产物已存在"分支, 复用统计
        # 由本登记补齐（该分支本身无法区分向量来自复制还是中断残留）
        self._fast2_jobs: Dict[str, int] = {}

    # ==================== Worker 侧写回统一入口（心跳 + 锁续期） ====================

    async def _reserve_replacement_task(self, doc: Dict[str, Any]) -> str:
        """重试/回滚先占有执行锁，再清除取消标记；旧任务未退出时拒绝提交。"""
        job_id = doc['id']
        token = uuid.uuid4().hex
        try:
            acquired = await asyncio.to_thread(_acquire_delete_job_lock, job_id, token)
        except Exception as exc:
            raise ParameterException(message="任务锁不可用，请稍后重试") from exc
        if not acquired:
            raise ParameterException(message="上一任务仍在停止中，请稍后重试或回滚")
        try:
            current = await self.document_service.get_document_entry(job_id)
            if not current or current.get('status') != 'failed':
                raise ParameterException(message="文档状态已变化，请刷新后重试")
            doc['celery_task_id'] = token
            await self.document_service.save_document(doc, bypass_guard=True)
            return token
        except Exception:
            _release_job_lock(job_id, token)
            raise

    async def _save(self, doc: Dict[str, Any], bypass_guard: bool = False) -> Dict[str, Any]:
        """Worker 侧整文档保存: 打心跳 → 委托 save_document → 续期执行锁。

        心跳（heartbeat_at）供 Web 侧僵尸巡检判定 Worker 存活; 仅流水线
        （Worker 侧）写回使用本入口, Web 侧提交/重试仍走 service.* 原生方法。
        """
        doc["heartbeat_at"] = self.document_service.now_time()
        saved = await self.document_service.save_document(doc, bypass_guard=bypass_guard)
        self._note_cancel_state(saved)
        if self._execution_token:
            _refresh_job_lock(saved["id"], self._execution_token)
        return saved

    async def _update(self, job_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Worker 侧字段级更新: 打心跳 → 委托 update_document → 续期执行锁。"""
        fields = {**fields, "heartbeat_at": self.document_service.now_time()}
        updated = await self.document_service.update_document(job_id, fields)
        if updated:
            self._note_cancel_state(updated)
            if self._execution_token:
                _refresh_job_lock(job_id, self._execution_token)
        return updated

    async def submit_conversion(
            self,
            *,
            file_bytes: bytes,
            filename: str,
            content_type: Optional[str],
            do_ocr: bool = True,
            force_ocr: bool = False,
            enable_vlm: bool = False,
    ) -> Dict[str, Any]:
        """提交 PDF 转换任务: 校验 → 落盘 → 建条目 → 分发 Celery 任务。

        :return: 任务摘要信息（job_id/status/filename/page_count/parts）
        :raises ParameterException: 文件参数不合法（预检发现重名亦走此分支）
        :raises DataAlreadyExistsException: 并发场景下锁内权威校验发现文件名重复
        """
        service = self.document_service

        # 兜底参数校验
        if not filename:
            raise ParameterException(message="未提供文件名")
        # 文件名清洗: 客户端文件名可能携带路径分隔符或 ../, 仅保留 basename
        filename = sanitize_upload_filename(filename)
        if not (content_type == "application/pdf" or filename.lower().endswith(".pdf")):
            raise ParameterException(message="仅支持 PDF 文件")
        if not file_bytes:
            raise ParameterException(message="文件内容为空")
        # PDF 魔数校验: content_type 与扩展名均可被客户端伪造, 仅文件头可信
        # （PDF 规范允许 %PDF- 出现在前 1024 字节内任意位置, 故用包含判断）
        if b"%PDF-" not in file_bytes[:1024]:
            raise ParameterException(message="不是有效的 PDF 文件（文件头校验失败）")
        # 重名预检（快速失败, 避免重名文件白跑页数统计与落盘）:
        # 权威校验在 service.create_document 的跨进程锁内, 防并发同名上传双双通过
        canonical_name = filename.lower()
        for doc in (await service.load_all()).values():
            if doc.get("filename", "").lower() == canonical_name:
                raise ParameterException(message=f"文件名 '{filename}' 已存在, 请修改文件名后上传")

        # 获取文档页数（移交线程池, 不阻塞事件循环; 损坏/加密 PDF 统一转为友好提示）
        try:
            page_count = await asyncio.to_thread(get_pdf_page_count, file_bytes)
        except Exception as exc:
            LOGGER.warning(f"PDF 页数解析失败: {filename}, {type(exc).__name__}: {exc}")
            raise ParameterException(message="PDF 无法解析, 文件可能已损坏或受密码保护")

        # 算术推导子文档数: 提交时只需要数量, 无需真切（Worker 执行时会按同样
        # 规则重新 split_pdf）。旧实现在此完整预切一遍随即丢弃, 白耗 CPU 且
        # 切分期间原始字节 + 全部切片字节同时驻留, 内存峰值约翻倍
        total_parts = max(1, math.ceil(page_count / PROJECT_CONFIG.PDF_SPLIT_MAX_PAGES))

        # 创建文档ID（文件名+时间, 确保ID全局唯一）
        job_id = "doc-" + hashlib.md5(f"{filename}|{time.time_ns()}".encode()).hexdigest()[:16]

        # 源文件落盘: input/<job_id>/<filename>（大文件写盘移交线程池, 不阻塞事件循环）
        input_dir = Path(PROJECT_CONFIG.RAG_INPUT_DIR) / job_id
        input_dir.mkdir(parents=True, exist_ok=True)
        input_file = input_dir / filename
        # 纵深兜底: 校验落盘目标仍位于留档目录内（防御路径穿越的未知绕过）
        if not input_file.resolve().is_relative_to(input_dir.resolve()):
            raise ParameterException(message="文件名不合法")
        await asyncio.to_thread(input_file.write_bytes, file_bytes)

        doc_entry = service.make_doc_entry(job_id, filename, str(input_file.resolve()))
        doc_entry["enable_vlm"] = enable_vlm
        doc_entry["do_ocr"] = do_ocr
        doc_entry["force_ocr"] = force_ocr
        doc_entry["page_count"] = page_count
        doc_entry["total_parts"] = total_parts
        doc_entry["completed_parts"] = 0
        # 记录内容指纹: 首次增量更新即可走"文件未变化"快速通道（否则要等
        # 第一次更新后才写入, 首更白白重跑一遍完整流水线）
        doc_entry["file_sha256"] = hashlib.sha256(file_bytes).hexdigest()
        # 先以 queued 态建条目: 表示"已落盘、待派发确认"。随后立即升级为正式
        # 处理态（splitting/parsing）再派发; 派发失败立即标 failed（防僵尸文档）
        doc_entry["status"] = "queued"
        # 原子创建: 重名权威校验 + 唯一约束兜底在数据库侧完成, 防并发同名上传双双通过
        # （重名时抛 DataAlreadyExistsException, 视图层统一转为 DataAlreadyExistsResponse）
        await service.create_document(doc_entry)

        # 先写正式处理态再派发（与 retry_document 的安全顺序一致）: 消息一旦投出,
        # Worker 可能瞬间完成并写回终态; 若之后再用本函数的内存状态覆盖 status,
        # 会把 complete/failed 打回 parsing（成功文档随后被巡检误标 failed）。
        # 因此 send_task 之后本流程只允许写 celery_task_id, 不再触碰 status。
        final_status = "splitting" if total_parts > 1 else "parsing"
        await service.update_document(job_id, {"status": final_status})

        # 分发 Celery 任务（Worker 会读取仅携带 job_id 的消息，从而从留档目录中读取字节流
        from celery_scheduler.celery_worker import celery
        try:
            async_result = celery.send_task(
                PROCESS_DOCUMENT_TASK,
                kwargs={"job_id": job_id},
            )
        except Exception as exc:
            # 派发失败（如消息队列不可用）: 此刻消息确定未投出, 不存在 Worker
            # 并发写回, 立即标 failed 防止文档滞留 parsing 成僵尸
            LOGGER.error(f"Celery 任务派发失败: {filename}, {type(exc).__name__}: {exc}")
            await service.update_document(job_id, {
                "status": "failed",
                "summary": "任务派发失败（消息队列不可用）, 请重试",
                "updated_at": service.now_time(),
            })
            raise ParameterException(message="任务派发失败, 请稍后重试")
        # 派发成功后只回写 Celery 任务ID, 不再触碰 status: task_id 与 Worker
        # 写回的终态字段不相交（字段级合并互不覆盖）, 竞态无从发生
        await service.update_document(job_id, {"celery_task_id": async_result.id})

        LOGGER.info(f"提交转换任务: {filename} (job_id={job_id}, 页数={page_count}), 子文档数={total_parts}")
        return {
            "job_id": job_id,
            "filename": filename,
            "page_count": page_count,
            "parts": total_parts,
            "status": final_status,
        }

    async def retry_document(self, job_id: str) -> Dict[str, Any]:
        """重试失败文档: 校验 → 重置文档状态 → 从源文件重跑或从中断阶段续跑。

        解析产物完整（产物目录 + 清洗后 markdown + 侧车均在）时进入**续跑**
        模式: 跳过内容解析, 由后处理管道按各阶段产物存在性决定从哪个
        阶段恢复（术语/多模态/分块/嵌入, 已完成的阶段直接跳过）——
        例如嵌入阶段失败的重试直接从嵌入开始, 不重跑数十分钟的解析。
        产物不完整时回退为从源文件（input/<job_id>/<filename>）重跑完整
        流水线, 沿用原有解析配置（OCR/分块策略/VLM 等）; 该路径源文件
        缺失（未留档的旧文档条目）时无法重试, 需重新上传。

        :return: 任务摘要信息（job_id/status/filename/page_count/parts）
        :raises NotFoundException: 文档不存在
        :raises ParameterException: 文档非失败状态或（全量重跑路径下）源文件缺失
        """
        service = self.document_service
        doc = await service.get_document_entry(job_id)
        if not doc:
            raise NotFoundException(message=f"文档不存在: {job_id}")
        if doc.get("status") != "failed":
            raise ParameterException(message=f"仅失败状态的文档可以重试（当前状态: {doc.get('status')}）")

        # 续跑判定: 解析产物完整 → 无需重新解析, 也不依赖源文件
        resumable = service._resume_artifacts_ready(doc)

        # 校验提交时留档的源文件存在（分发前快速失败;
        # 字节流由 Worker 在执行时从该路径自行读取, 不随消息传递）。
        # 仅全量重跑路径需要; 续跑路径的输入来自产物目录与文档记录
        input_path = doc.get("input_path") or ""
        if not resumable and (not input_path or not Path(input_path).is_file()):
            raise ParameterException(message="源文件缺失（旧文档条目未留档 input）, 无法重试, 请重新上传文件")

        # 重置文档状态（保留解析配置与创建信息）
        now = service.now_time()
        doc["status"] = "terminology" if resumable else "parsing"
        # 清除取消标记: 被取消的文档（cancel_requested=True）重试时若不清除,
        # 重投递任务会在首个取消检查点自行退出, 且后续字段写回被防覆盖守卫压回
        doc["cancel_requested"] = False
        doc["resume"] = resumable
        doc["summary"] = "-"
        doc["error_trace"] = ""
        doc["chunks_count"] = None
        doc["completed_parts"] = 0
        doc["updated_at"] = now
        # 阶段计时不做统一清零: 已成功的阶段保留上一轮计时, 本次被重跑的阶段
        # （失败阶段及其后续）在执行时覆写为新计时。如此无论重跑还是续跑, 文档
        # 到达 complete 时每个实际执行过的阶段都有计时——续跑被产物跳过的阶段
        # 沿用上一轮计时, 不再出现"跳过即无计时"的空档。
        # （全量重跑会重新执行解析与后处理, 计时自然整体覆写, 同样无需清零。）
        if not resumable:
            doc["content_length"] = None
        task_token = await self._reserve_replacement_task(doc)

        # 重新分发 Celery 任务（消息仅携带 job_id; Worker 依据 resume 标记
        # 决定续跑或从 input/ 留档重读源文件重跑完整流水线）
        from celery_scheduler.celery_worker import celery
        try:
            async_result = celery.send_task(
                PROCESS_DOCUMENT_TASK,
                kwargs={"job_id": job_id},
                task_id=task_token,
            )
        except Exception as exc:
            # 状态已先重置为处理中，但消息可能因 Redis/Broker 不可用而未投递。
            # 必须恢复 failed，否则前端会永久显示 parsing/terminology，且用户
            # 无法再次点击重试。
            LOGGER.error(
                f"Celery 任务派发失败（重试文档）: job_id={job_id}, "
                f"{type(exc).__name__}: {exc}"
            )
            await service.update_document(job_id, {
                "status": "failed",
                "summary": "重试任务派发失败（消息队列不可用）, 请稍后重试",
                "error_trace": traceback.format_exc()[-5000:],
                "updated_at": service.now_time(),
            })
            _release_job_lock(job_id, task_token)
            raise ParameterException(message="重试任务派发失败, 请稍后重试") from exc
        # 回写 Celery 任务ID 用字段级更新（浅合并, 避免旧快照覆盖 Worker 写入）
        await service.update_document(job_id, {"celery_task_id": async_result.id})

        mode = "从中断阶段续跑" if resumable else "源文件重跑"
        LOGGER.info(f"重试文档（{mode}）: {doc['filename']} (job_id={job_id})")
        await service.add_history(f"重试文档（{mode}）: {doc['filename']}")
        return {
            "job_id": job_id,
            "status": doc["status"],
            "filename": doc["filename"],
            "page_count": doc.get("page_count"),
            "parts": doc.get("total_parts", 1),
        }

    # ==================== 增量更新 ====================

    # prev 归档字段快照收录的字段（回滚时据此恢复文档行; 均为模型可写字段,
    # 时间类以字符串收录, 写入时由 CRUD 层统一转 datetime）
    _SNAPSHOT_FIELDS = (
        "status", "summary", "content_length", "chunks_count",
        "page_count", "total_parts", "completed_parts",
        "terminology_total_batches", "terminology_completed_batches",
        "analyzing_stage_skipped", "sidecar", "artifacts_file", "chunks_file",
        "output_path", "input_path", "do_ocr", "force_ocr", "enable_vlm",
        "file_sha256",
        "parse_start_time", "parse_end_time", "parse_duration",
        "term_start_time", "term_end_time",
        "analyze_start_time", "analyze_end_time", "analyze_duration",
        "chunk_start_time", "chunk_end_time",
        "embed_start_time", "embed_end_time", "process_end_time",
    )

    # 快速通道②复制回的后处理产物（按阶段顺序; 仅复制 prev 中实际存在的文件,
    # 缺失的产物交由对应阶段正常生成——如 prev 术语提取失败, 本次照常重试）
    _REUSABLE_ARTIFACTS = (
        "terminology.md", "terminology_index.json", "summary.json",
        "multimodal_analysis.json", "chunks.json",
    )

    async def submit_update(
            self,
            *,
            job_id: str,
            file_bytes: bytes,
            filename: str,
            content_type: Optional[str],
    ) -> Dict[str, Any]:
        """提交文档增量更新: 校验 → prev 归档 → 新版本落盘 → 重置字段 → 分发任务。

        仅 complete 文档可更新; 解析配置沿用原文档行
        （do_ocr/force_ocr/enable_vlm）, **job_id 与 filename 保持不变**——
        向量库以 job_id 为索引键, 文件名唯一约束与引用来源因此稳定,
        前端轮询/状态机零改动即复用。

        "增量"以存在健康旧版本为前提: 首次失败的文档没有旧版本可增量,
        更新失败的文档应先回滚恢复（或重试同一文件）再更新, 故 failed
        一律拒绝, 避免"问答仍用旧版本"等语义失真。

        快速通道①: 上传文件 SHA256 与记录版本一致 → 直接返回 unchanged=True,
        不归档不分发（内容未变, 重处理纯浪费）。

        归档语义（文档原子性的保障, 见 _archive_current_version）:
        现有产物整体改名为 <job_id>.prev（同盘瞬时）+ 字段快照落盘,
        更新失败时可一键回滚。

        :return: 任务摘要（job_id/status/filename/page_count/parts/unchanged）
        :raises NotFoundException: 文档不存在
        :raises ParameterException: 状态不可更新 / 文件不合法 / 派发失败
        """
        service = self.document_service
        doc = await service.get_document_entry(job_id)
        if not doc:
            raise NotFoundException(message=f"文档不存在: {job_id}")
        # 仅 complete 可更新（见 docstring）: 首次失败的文档没有旧版本可增量,
        # 更新失败的文档应先回滚（恢复为 complete）或重试, 再来更新
        status = doc.get("status")
        if status != "complete":
            if status == "failed":
                raise ParameterException(
                    message="失败文档不能直接增量更新: 请先重试, 或回滚到上一版本后再更新"
                )
            raise ParameterException(message=f"处理中的文档不能更新（当前状态: {status}）")

        # ---- 文件校验（与 submit_conversion 同口径）----
        original_name = doc["filename"]
        if not filename:
            filename = original_name
        filename = sanitize_upload_filename(filename)
        if not (content_type == "application/pdf" or filename.lower().endswith(".pdf")):
            raise ParameterException(message="仅支持 PDF 文件")
        if not file_bytes:
            raise ParameterException(message="文件内容为空")
        if b"%PDF-" not in file_bytes[:1024]:
            raise ParameterException(message="不是有效的 PDF 文件（文件头校验失败）")

        # ---- 快速通道①: 字节一致 → 免重处理 ----
        new_sha = hashlib.sha256(file_bytes).hexdigest()
        if doc.get("file_sha256") == new_sha:
            LOGGER.info(f"增量更新快速通道①: 文件与现版本一致, 跳过: {original_name} (job_id={job_id})")
            await service.add_history(f"增量更新跳过（文件未变化）: {original_name}")
            return {
                "job_id": job_id,
                "status": status,
                "filename": original_name,
                "page_count": doc.get("page_count"),
                "parts": doc.get("total_parts", 1),
                "unchanged": True,
            }

        # ---- 页数与分片数（以新文件为准）----
        try:
            page_count = await asyncio.to_thread(get_pdf_page_count, file_bytes)
        except Exception as exc:
            LOGGER.warning(f"PDF 页数解析失败（增量更新）: {original_name}, {type(exc).__name__}: {exc}")
            raise ParameterException(message="PDF 无法解析, 文件可能已损坏或受密码保护")
        total_parts = max(1, math.ceil(page_count / PROJECT_CONFIG.PDF_SPLIT_MAX_PAGES))

        # ---- prev 归档事务（同步文件操作, 移交线程池）----
        await asyncio.to_thread(self._archive_current_version, doc)

        try:
            # ---- 新版本源文件落盘: input/<job_id>/<原文件名> ----
            input_dir = Path(PROJECT_CONFIG.RAG_INPUT_DIR) / job_id
            input_dir.mkdir(parents=True, exist_ok=True)
            input_file = input_dir / original_name
            if not input_file.resolve().is_relative_to(input_dir.resolve()):
                raise ParameterException(message="文件名不合法")
            await asyncio.to_thread(input_file.write_bytes, file_bytes)

            # ---- 重置文档状态: 保留 job_id/filename/解析配置/更新历史, 其余归零。
            # bypass_guard: 被取消的失败文档（cancel_requested=True）也允许更新,
            # 且取消标记必须清除, 否则重投递任务会在首个检查点自行退出
            now = service.now_time()
            doc["status"] = "splitting" if total_parts > 1 else "parsing"
            doc["is_updating"] = True
            doc["cancel_requested"] = False
            doc["resume"] = False
            doc["file_sha256"] = new_sha
            doc["summary"] = "-"
            doc["error_trace"] = ""
            doc["content_length"] = None
            doc["chunks_count"] = None
            doc["completed_parts"] = 0
            doc["page_count"] = page_count
            doc["total_parts"] = total_parts
            doc["input_path"] = str(input_file.resolve())
            doc["output_path"] = ""
            doc["sidecar"] = {}
            doc["artifacts_file"] = ""
            doc["chunks_file"] = ""
            # 新版本 = 全新一轮处理, 阶段计时整体清零（与 retry 的"保留上轮计时"
            # 不同: 更新后旧计时不再属于当前版本, 保留会误导）。时间点字段按流水线
            # 惯例以空串清零（sanitize 统一转 None）; 时长字段为 FloatField,
            # 必须直接置 None——空串写 FLOAT 列会在驱动层抛 float('')
            for time_key in (
                "parse_start_time", "parse_end_time",
                "term_start_time", "term_end_time",
                "analyze_start_time", "analyze_end_time",
                "chunk_start_time", "chunk_end_time",
                "embed_start_time", "embed_end_time", "process_end_time",
            ):
                doc[time_key] = ""
            doc["parse_duration"] = None
            doc["analyze_duration"] = None
            doc["updated_at"] = now
            await service.save_document(doc, bypass_guard=True)
        except Exception as exc:
            # 归档已完成而其后步骤失败 → 撤销归档恢复旧版本, 不留"目录已归档
            # 而文档行未写入"的残缺状态（该状态下产物路径与术语索引全部失联,
            # 且回滚入口因状态仍为 complete 而不可达）
            if not isinstance(exc, ParameterException):
                LOGGER.error(
                    f"增量更新提交中断, 撤销 prev 归档: {original_name} "
                    f"(job_id={job_id}): {type(exc).__name__}: {exc}"
                )
            await asyncio.to_thread(self._undo_archive, job_id)
            if isinstance(exc, ParameterException):
                raise
            raise ParameterException(
                message="增量更新提交失败: 文档状态写入异常, 旧版本已恢复, 请稍后重试"
            )

        # ---- 分发 Celery 任务（消息仅携带 job_id, 与新上传完全同一条流水线）----
        from celery_scheduler.celery_worker import celery
        try:
            async_result = celery.send_task(
                PROCESS_DOCUMENT_TASK,
                kwargs={"job_id": job_id},
            )
        except Exception as exc:
            # 派发失败: 归档已完成 → 标记失败后前端可一键回滚恢复旧版本
            LOGGER.error(f"Celery 任务派发失败（增量更新）: {original_name}, {type(exc).__name__}: {exc}")
            await service.update_document(job_id, {
                "status": "failed",
                "summary": "任务派发失败（消息队列不可用）, 可重试或回滚到上一版本",
                "is_updating": False,
                "updated_at": service.now_time(),
            })
            raise ParameterException(message="任务派发失败, 请稍后重试")
        await service.update_document(job_id, {"celery_task_id": async_result.id})

        LOGGER.info(
            f"提交增量更新: {original_name} (job_id={job_id}, 页数={page_count}), 子文档数={total_parts}"
        )
        await service.add_history(f"提交增量更新: {original_name}")
        return {
            "job_id": job_id,
            "status": doc["status"],
            "filename": original_name,
            "page_count": page_count,
            "parts": total_parts,
            "unchanged": False,
        }

    def _archive_current_version(self, doc: Dict[str, Any]) -> None:
        """prev 归档事务（同步文件操作, 由线程池调用）。

        唯一调用方 submit_update 的入口门已收窄为 complete 文档, 归档时必有
        完整旧版本可留档: 当前产物目录与源文件留档目录**改名**为 <job_id>.prev
        （同盘改名为瞬时原子操作, 无复制开销, 更新失败可整体回滚）, 并在 prev
        产物目录写入字段快照 doc_snapshot.json（回滚恢复文档行的依据）; 残留
        prev（正常不应存在——更新成功时已删除）先行清除再归档。

        刻意不使用跨目录复制: 改名失败即归档失败, 不会出现"复制一半"的残缺
        prev; 而复制大产物目录（数百 MB embeddings.json）既慢又有中断风险。
        """
        job_id = doc["id"]
        if doc.get("status") != "complete":
            # 防御性守卫: 入口门已限 complete, 若约束被放宽而误入非 complete
            # 文档, 宁可跳过归档也不留档残缺产物（避免产生错误 prev）
            LOGGER.warning(
                f"prev 归档遇到非 complete 文档, 跳过归档: {job_id} (status={doc.get('status')})"
            )
            return
        out_base = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR)
        in_base = Path(PROJECT_CONFIG.RAG_INPUT_DIR)
        cur_out, prev_out = out_base / job_id, out_base / f"{job_id}{PREV_SUFFIX}"
        cur_in, prev_in = in_base / job_id, in_base / f"{job_id}{PREV_SUFFIX}"

        for prev in (prev_out, prev_in):
            if prev.exists():
                shutil.rmtree(prev, ignore_errors=True)
        if cur_out.is_dir():
            cur_out.rename(prev_out)
        if cur_in.is_dir():
            cur_in.rename(prev_in)
        if prev_out.is_dir():
            snapshot = {k: doc.get(k) for k in self._SNAPSHOT_FIELDS}
            snapshot["snapshot_at"] = self.document_service.now_time()
            try:
                (prev_out / "doc_snapshot.json").write_text(
                    json.dumps(snapshot, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as e:
                LOGGER.error(f"prev 归档字段快照写入失败（{job_id}）: {e}")

    @staticmethod
    def _undo_archive(job_id: str) -> None:
        """撤销 prev 归档（submit_update 归档后续步骤失败时的补偿, 线程池调用）。

        把 <job_id>.prev 改名回 <job_id>（产物目录与源文件留档目录）, 并删除
        归档之后新写入的新版本源文件目录; 恢复后磁盘与未更新的文档行重新一致,
        旧版本继续完整服务（向量库在整个过程中未被触碰）。某侧不存在 prev
        （该侧归档未发生）时绝不触碰现有目录——补偿操作不得造成二次破坏。
        """
        for base in (Path(PROJECT_CONFIG.RAG_OUTPUT_DIR), Path(PROJECT_CONFIG.RAG_INPUT_DIR)):
            cur, prev = base / job_id, base / f"{job_id}{PREV_SUFFIX}"
            if not prev.is_dir():
                continue
            try:
                if cur.is_dir():
                    shutil.rmtree(cur, ignore_errors=True)
                prev.rename(cur)
            except Exception as e:
                LOGGER.error(f"撤销 prev 归档失败（{job_id}）: {base}: {e}")
        # 归档时写入的字段快照随产物目录回到了原位, 现行版本不应携带快照
        try:
            snapshot = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR) / job_id / "doc_snapshot.json"
            if snapshot.is_file():
                snapshot.unlink()
        except Exception as e:
            LOGGER.warning(f"撤销归档后清理字段快照失败（{job_id}）: {e}")

    @staticmethod
    def _remove_prev_archives(job_id: str) -> None:
        """更新成功后删除 prev 归档（产物目录 + 源文件留档目录, 尽力而为）。

        仅由流水线成功收尾调用; 删除失败（如 Windows 文件占用）仅告警——
        残留 prev 不影响正确性（文档已 complete, 不满足回滚展示条件）,
        且下次更新的归档事务会先清除残留。
        """
        for base in (PROJECT_CONFIG.RAG_OUTPUT_DIR, PROJECT_CONFIG.RAG_INPUT_DIR):
            prev = Path(base) / f"{job_id}{PREV_SUFFIX}"
            try:
                if prev.is_dir():
                    shutil.rmtree(prev)
            except Exception as e:
                LOGGER.warning(f"prev 归档删除失败（{prev}）: {e}")

    # ==================== 回滚到上一版本 ====================

    async def submit_rollback(self, job_id: str) -> Dict[str, Any]:
        """提交回滚到上一版本: 校验 failed 状态与 prev 归档齐备 → 分发短任务。

        回滚执行体在 Worker（execute_rollback）: 先用 prev 的 embeddings.json
        重写向量库 → 恢复产物/留档目录 → 从字段快照恢复文档行。向量是问答
        正确性的最终载体, 必须最先恢复; 该步失败则归档与文档行一律不动,
        prev 仍在, 可再次回滚。

        短任务同样经过 embedding 状态, 前端现有轮询机制即可感知进度。

        :return: 任务摘要（job_id/status/filename/page_count/parts）
        :raises NotFoundException: 文档不存在
        :raises ParameterException: 非失败状态 / prev 归档不完整 / 派发失败
        """
        service = self.document_service
        doc = await service.get_document_entry(job_id)
        if not doc:
            raise NotFoundException(message=f"文档不存在: {job_id}")
        if doc.get("status") != "failed":
            raise ParameterException(message=f"仅失败状态的文档可以回滚（当前状态: {doc.get('status')}）")
        prev_out = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR) / f"{job_id}{PREV_SUFFIX}"
        if not (prev_out / "doc_snapshot.json").is_file() or not (prev_out / "embeddings.json").is_file():
            raise ParameterException(message="上一版本归档不完整, 无法回滚, 请重试更新或重新上传")

        # 置为 embedding（短任务的最末阶段）+ 清除取消标记（被取消的失败文档
        # 同样允许回滚）; bypass_guard 防取消守卫把状态写回压成 failed
        doc["status"] = "embedding"
        doc["summary"] = "正在回滚到上一版本"
        doc["error_trace"] = ""
        doc["cancel_requested"] = False
        doc["is_updating"] = False
        doc["updated_at"] = service.now_time()
        task_token = await self._reserve_replacement_task(doc)

        from celery_scheduler.celery_worker import celery
        try:
            async_result = celery.send_task(
                ROLLBACK_DOCUMENT_TASK,
                kwargs={"job_id": job_id},
                task_id=task_token,
            )
        except Exception as exc:
            LOGGER.error(f"Celery 任务派发失败（回滚）: {job_id}, {type(exc).__name__}: {exc}")
            await service.update_document(job_id, {
                "status": "failed",
                "summary": "回滚任务派发失败（消息队列不可用）, 请重试",
                "updated_at": service.now_time(),
            })
            _release_job_lock(job_id, task_token)
            raise ParameterException(message="任务派发失败, 请稍后重试")
        await service.update_document(job_id, {"celery_task_id": async_result.id})

        LOGGER.info(f"提交回滚: {doc['filename']} (job_id={job_id})")
        await service.add_history(f"提交回滚到上一版本: {doc['filename']}")
        return {
            "job_id": job_id,
            "status": "embedding",
            "filename": doc["filename"],
            "page_count": doc.get("page_count"),
            "parts": doc.get("total_parts", 1),
        }

    async def execute_rollback(self, job_id: str, execution_token: Optional[str] = None) -> Dict[str, Any]:
        """按 job_id 执行回滚（Celery 任务执行体, 双层重复任务防护与 process_document 同款）。"""
        self._execution_token = execution_token or uuid.uuid4().hex
        with _ACTIVE_JOB_LOCK:
            if job_id in _ACTIVE_JOB_IDS:
                error = f"任务已在执行中, 跳过重复投递: job_id={job_id}"
                LOGGER.warning(error)
                return {"success": False, "error": error}
            _ACTIVE_JOB_IDS.add(job_id)
        try:
            if not _acquire_job_lock(job_id, self._execution_token):
                error = f"任务已在其他进程执行, 跳过重复投递: job_id={job_id}"
                LOGGER.warning(error)
                return {"success": False, "error": error}
            try:
                return await self._run_rollback_inner(job_id)
            finally:
                _release_job_lock(job_id, self._execution_token)
        finally:
            with _ACTIVE_JOB_LOCK:
                _ACTIVE_JOB_IDS.discard(job_id)

    async def _run_rollback_inner(self, job_id: str) -> Dict[str, Any]:
        """回滚执行体: ① prev 向量重写向量库 → ② 目录改名还原 → ③ 字段快照恢复。

        顺序即正确性优先级: 向量最先恢复（问答以它为准）; 任一步失败都把
        文档标为 failed 且保持 prev 归档不动, 用户可再次回滚。
        """
        service = self.document_service
        doc = await service.get_document_entry(job_id)
        if not doc:
            return {"success": False, "error": f"文档不存在: job_id={job_id}"}
        submitted = doc.get('status') == 'embedding' and doc.get('celery_task_id') == self._execution_token
        if doc.get("status") != "failed" and not submitted:
            return {"success": False, "error": f"文档不属于当前回滚任务（当前状态: {doc.get('status')}）"}

        out_base = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR)
        in_base = Path(PROJECT_CONFIG.RAG_INPUT_DIR)
        prev_out = out_base / f"{job_id}{PREV_SUFFIX}"
        prev_in = in_base / f"{job_id}{PREV_SUFFIX}"
        snapshot_file = prev_out / "doc_snapshot.json"
        embeddings_file = prev_out / "embeddings.json"
        if not snapshot_file.is_file() or not embeddings_file.is_file():
            await self._update(job_id, {"status": "failed", "summary": "回滚失败: 上一版本归档不完整"})
            return {"success": False, "error": "prev 归档不完整"}

        # 心跳 + 锁续期（短任务通常秒级, 但向量重写大文档可能分钟级）
        await self._update(job_id, {"summary": "正在回滚到上一版本"})
        filename = doc["filename"]
        await service.add_history(f"开始回滚: {filename}")

        # ---- ① 向量库恢复: 加载 prev 向量产物, 先删后写（与流水线阶段 4 同款）----
        try:
            emb_data = json.loads(embeddings_file.read_text(encoding="utf-8"))
            chunks = [emb_data[k] for k in sorted(emb_data)]
        except Exception as e:
            LOGGER.error(f"回滚失败: prev 向量产物不可读 ({job_id}): {e}")
            await self._update(job_id, {"status": "failed", "summary": f"回滚失败: 上一版本向量产物不可读 ({e})"})
            return {"success": False, "error": str(e)}
        if not chunks or not all((c or {}).get("vector") for c in chunks):
            await self._update(job_id, {"status": "failed", "summary": "回滚失败: 上一版本向量产物不完整"})
            return {"success": False, "error": "prev embeddings.json 不完整"}
        try:
            from applications.jiayueyang.rag.milvus_store import (
                delete_by_doc_id,
                upsert_chunks as store_chunks,
            )
            delete_by_doc_id(job_id)
            store_chunks(chunks, file_path=filename, doc_id=job_id)
        except Exception as e:
            LOGGER.error(f"回滚失败: 向量库写入失败 ({job_id}): {e}\n{traceback.format_exc()}")
            await self._update(job_id, {"status": "failed", "summary": f"回滚失败: 向量库写入失败 -- {e}"})
            await service.add_history(f"回滚失败: {filename} -- {e}")
            return {"success": False, "error": str(e)}

        # ---- ② 磁盘归档还原: prev 目录改名回正式目录（先清当前失败产物）----
        cur_out, cur_in = out_base / job_id, in_base / job_id
        try:
            if cur_out.exists():
                shutil.rmtree(cur_out)
            if cur_in.exists():
                shutil.rmtree(cur_in)
            prev_out.rename(cur_out)
            if prev_in.is_dir():
                prev_in.rename(cur_in)
        except OSError as e:
            # 向量已恢复而目录还原失败: 极端情形（文件占用）, 文档保持 failed,
            # 但产物目录状态已不一致——记录明细供人工处置
            LOGGER.error(f"回滚: 目录还原失败 ({job_id}): {e}\n{traceback.format_exc()}")
            await self._update(job_id, {
                "status": "failed",
                "summary": f"回滚部分完成: 向量已恢复, 产物目录还原失败 -- {e}",
            })
            return {"success": False, "error": str(e)}

        # ---- ③ 字段快照恢复文档行（bypass 守卫; 快照内路径随目录改名重新生效）----
        try:
            snapshot = json.loads((cur_out / "doc_snapshot.json").read_text(encoding="utf-8"))
        except Exception as e:
            LOGGER.error(f"回滚: 字段快照不可读 ({job_id}): {e}")
            await self._update(job_id, {"status": "failed", "summary": f"回滚部分完成: 字段快照不可读 -- {e}"})
            return {"success": False, "error": str(e)}
        restore = {k: snapshot[k] for k in self._SNAPSHOT_FIELDS if k in snapshot}
        restore.update({
            "id": job_id,
            "status": "complete",
            "is_updating": False,
            "resume": False,
            "cancel_requested": False,
            "error_trace": "",
            "updated_at": service.now_time(),
        })
        await service.save_document(restore, bypass_guard=True)

        await service.add_history(f"回滚完成（已恢复上一版本向量与产物）: {filename}")
        LOGGER.info(f"回滚完成: {filename} (job_id={job_id}, 恢复向量 {len(chunks)} 个)")
        return {"success": True, "job_id": job_id, "chunks_count": len(chunks)}

    async def process_document(self, job_id: str, execution_token: Optional[str] = None) -> Dict[str, Any]:
        """按 job_id 执行处理流水线（Celery 任务执行体, 双层重复任务防护）。

        防护语义（两层, 均命中即放弃执行并正常 ack）:
        1. 进程内快速防护 _ACTIVE_JOB_IDS: 同一 worker 进程内的重复投递;
        2. Redis 跨进程权威锁: 消息重投递落到其他 worker 进程时同样拦下。
           锁以 execution_token（Celery task id）为凭证, 重投递任务 task_id
           不变 → 可重入接管续跑; 不同 token 的并行执行（用户重复提交）被拒。
        无论内层成功/失败/异常, 退出时移除执行标记并释放锁。

        :param execution_token: Celery 任务ID（任务入口传入）; 缺省时生成临时 token

        返回值约定（与 zsj Celery 任务一致）: dict, success=False 表示业务失败。
        """
        process_started = time.perf_counter()
        process_started_at = _now_iso()
        LOGGER.info(
            f"RAG 文档解析任务开始: job_id={job_id}; "
            f"start_at={process_started_at}"
        )
        self._execution_token = execution_token or uuid.uuid4().hex
        with _ACTIVE_JOB_LOCK:
            if job_id in _ACTIVE_JOB_IDS:
                error = f"任务已在执行中, 跳过重复投递: job_id={job_id}"
                LOGGER.warning(error)
                return {"success": False, "error": error}
            _ACTIVE_JOB_IDS.add(job_id)
        try:
            if not _acquire_job_lock(job_id, self._execution_token):
                error = f"任务已在其他进程执行, 跳过重复投递: job_id={job_id}"
                LOGGER.warning(error)
                return {"success": False, "error": error}
            try:
                return await self._process_document_inner(job_id)
            finally:
                _release_job_lock(job_id, self._execution_token)
        finally:
            with _ACTIVE_JOB_LOCK:
                _ACTIVE_JOB_IDS.discard(job_id)
            process_ended_at = _now_iso()
            LOGGER.info(
                f"RAG 文档解析任务结束: job_id={job_id}; "
                f"end_at={process_ended_at}; "
                f"耗时={round((time.perf_counter() - process_started) * 1000, 1)} ms"
            )

    async def _process_document_inner(self, job_id: str) -> Dict[str, Any]:
        """process_document 的实际执行体（流水线本体）。

        执行策略: 从提交时落盘的留档目录（input/<job_id>/<filename>）读取
        源文件字节流 → 分片 → 单文档/分片解析 → 完整后处理管道。
        源文件缺失（未留档的旧文档条目）时标记失败。
        """
        service = self.document_service
        doc = await service.get_document_entry(job_id)
        if not doc:
            return {"success": False, "error": f"文档不存在: job_id={job_id}"}
        status = doc.get("status")
        if status in {"complete", "failed", "deleting"}:
            # task_acks_late 下，旧消息可能在 Worker 异常后重新投递。
            # 锁只能防止同一时刻的并发执行，不能说明这条消息仍然对应
            # 当前业务状态；终态任务必须在进入流水线前幂等跳过。
            LOGGER.info(
                f"任务状态为 {status}，跳过旧/重复解析任务: job_id={job_id}"
            )
            return {"success": True, "job_id": job_id, "skipped": status}
        # 初始化取消内存标记（派发前已被取消/删除的任务在此即被感知）
        self._note_cancel_state(doc)

        # 记录流水线启动时间（MySQL 单行表行级更新, 跨进程原子）
        await service.pipeline.set_start_time(datetime.now())

        # 续跑决策终判: retry 标记 resume 且解析产物仍完整才走续跑路径
        # （防重试分发后产物被外部清理）; 产物丢失则自动降级全量重跑。
        # 续跑路径不依赖源文件, 全量重跑路径需要源文件存在
        resume = bool(doc.get("resume")) and service._resume_artifacts_ready(doc)

        # 从留档目录读取源文件字节流（提交/重试时分发, 不再随 Celery 消息传递）
        input_path = doc.get("input_path") or ""
        input_file = Path(input_path)
        if not resume and (not input_path or not input_file.is_file()):
            doc["status"] = "failed"
            doc["summary"] = "源文件缺失, 无法执行流水线, 请重新上传"
            doc["is_updating"] = False  # 增量更新到此终止（旧版本向量仍在服务）
            doc["updated_at"] = service.now_time()
            await self._save(doc)
            return {"success": False, "error": doc["summary"]}

        try:
            if resume:
                # 从中断阶段续跑: 跳过内容解析, 后处理管道按产物存在性
                # 跳过已完成阶段（术语/多模态/分块/嵌入）
                await self._resume_post_parse_pipeline(job_id=job_id)
            else:
                file_bytes = input_file.read_bytes()
                parts = split_pdf(
                    file_bytes, doc["filename"],
                    max_pages=PROJECT_CONFIG.PDF_SPLIT_MAX_PAGES,
                )
                if len(parts) == 1:
                    # 未超切分阈值: 整篇直接解析
                    await self.run_background_process(job_id=job_id, file_bytes=file_bytes)
                else:
                    await self.process_split_document(job_id=job_id, parts=parts)
        except Exception as exc:
            LOGGER.error(f"文档处理任务异常: job_id={job_id}, {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
            return {"success": False, "error": str(exc)}
        finally:
            # 流水线结束, 清理启动时间（MySQL 单行表行级更新, 跨进程原子）
            await service.pipeline.set_start_time(None)

        # 增量更新终态收敛: 无论经哪条路径到达终态（取消提前退出 / 各阶段
        # 异常置 failed / 成功）都清除"更新中"标记。成功路径在阶段 4 收尾已清,
        # 此处兜底其余路径（防前端永久显示"更新中"）
        final_doc = await service.get_document_entry(job_id) or {}
        if final_doc.get("is_updating") and final_doc.get("status") in ("complete", "failed"):
            await service.update_document(job_id, {"is_updating": False})
            final_doc["is_updating"] = False

        # 重新加载最终状态判定成败
        if final_doc.get("status") == "complete":
            return {"success": True, "job_id": job_id, "chunks_count": final_doc.get("chunks_count")}
        return {"success": False, "error": final_doc.get("summary", "处理未完成")}

    # ==================== 取消检测（异步刷新 + 同步缓存 双通道）====================

    def _note_cancel_state(self, doc: Dict[str, Any]) -> None:
        """按写回结果维护内存取消标记（每次心跳写回后触发）。"""
        self._cancel_flags[doc["id"]] = (
            bool(doc.get("cancel_requested"))
            or doc.get("status") not in RagDocumentService.ACTIVE_STATUSES
        )

    async def refresh_cancel_state(self, job_id: str) -> bool:
        """检查点取消检测（异步上下文）: 查库刷新内存标记并返回是否已取消。

        取消以 cancel_requested 字段驱动（码化, 文案调整不会破坏判定）;
        文档被删除或状态离开处理中同样判定为取消（与原语义一致）。
        """
        doc = await self.document_service.get_document_entry(job_id)
        if doc is None:
            self._cancel_flags[job_id] = True
            return True
        self._note_cancel_state(doc)
        return self._cancel_flags.get(job_id, False)

    def is_cancelled_cached(self, job_id: str) -> bool:
        """同步检查点取消检测（docling 工作线程/回调）: 只读内存标记。

        标记由 _save/_update 心跳、refresh_cancel_state 阶段检查点与
        分片等待侧的周期刷新共同维护（见 _consume_progress）。
        """
        return self._cancel_flags.get(job_id, False)

    async def run_background_process(
            self,
            *,
            job_id: str,
            file_bytes: bytes,
    ) -> None:
        """单文档流程: 原生 docling 离线解析 → 后处理管道。"""
        service = self.document_service
        start_time = time.time()
        parse_started_at = _now_iso()
        parse_started = time.perf_counter()
        LOGGER.info(
            f"RAG 单文档解析开始: job_id={job_id}; start_at={parse_started_at}"
        )

        doc = await service.get_document_entry(job_id)
        if not doc:
            return
        filename = doc["filename"]

        doc["parse_start_time"] = service.now_time()
        doc = await self._save(doc)
        await service.add_history(f"开始处理: {filename}")
        LOGGER.info(f"后台处理开始: {filename} (job_id={job_id})")

        try:
            # 取消检查点
            if await self.refresh_cancel_state(job_id):
                await service.add_history(f"已取消: {filename}")
                return

            # 原生 docling 离线解析（产物目录以 job_id 命名, 转换在独立线程执行）
            await service.add_history(f"开始解析: {filename}")
            conversion_started = time.perf_counter()
            conversion_started_at = _now_iso()
            try:
                bundle = await convert_pdf_to_bundle(
                    file_bytes, filename, job_id,
                    do_ocr=doc.get("do_ocr", True),
                    force_ocr=doc.get("force_ocr", True),
                )
            finally:
                LOGGER.info(
                    f"RAG PDF内容解析结束: job_id={job_id}; "
                    f"start_at={conversion_started_at}; end_at={_now_iso()}; "
                    f"耗时={round((time.perf_counter() - conversion_started) * 1000, 1)} ms"
                )

            # 取消检查点
            if await self.refresh_cancel_state(job_id):
                await service.add_history(f"已取消: {filename}")
                return

            doc["markdown"] = bundle.markdown
            doc["summary"] = bundle.markdown.replace("\n", " ")[:15].strip() or "-"
            doc["content_length"] = len(bundle.markdown)
            doc["output_path"] = str(bundle.bundle_dir.resolve())
            doc["parse_end_time"] = service.now_time()
            doc["parse_duration"] = round(time.time() - start_time, 1)
            doc["updated_at"] = service.now_time()
            doc = await self._save(doc)
            await service.add_history(f"内容解析完成: {filename}")

            # 构建侧车文件
            try:
                from applications.jiayueyang.rag.sidecar import write_sidecar
                json_path = str(bundle.json_path) if bundle.json_path else None
                if not json_path or not Path(json_path).exists():
                    raise RuntimeError(f"结果包中未找到 Docling JSON ({bundle.bundle_dir})")
                sidecar = write_sidecar(
                    json_path,
                    str(bundle.bundle_dir),
                    engine="docling",
                    md_path=str(bundle.md_path) if bundle.md_path else None,
                )
                doc["sidecar"] = sidecar
                if bundle.artifacts_dir:
                    doc["artifacts_file"] = str(bundle.artifacts_dir)
                await service.add_history(f"侧车文件已生成: {filename}")
            except Exception as sidecar_err:
                await service.add_history(
                    f"侧车文件生成失败: {type(sidecar_err).__name__}: {sidecar_err}"
                )
                await service.add_history(f"堆栈: {traceback.format_exc()[-300:]}")
                raise

            # 执行共享后处理管道
            await self._run_post_parse_pipeline(
                doc=doc,
                job_id=job_id,
                markdown=bundle.markdown,
                enable_vlm=doc.get("enable_vlm", False),
                start_time=start_time,
            )
            LOGGER.info(f"后台处理完成: {filename} (分块数={doc.get('chunks_count')})")

        except Exception as exc:
            doc["status"] = "failed"
            doc["summary"] = f"{type(exc).__name__}: {exc}"
            doc["error_trace"] = traceback.format_exc()[-500:]
            doc["updated_at"] = service.now_time()
            doc = await self._save(doc)
            await service.add_history(f"异常: {type(exc).__name__}: {exc}")
            await service.add_history(f"失败: {filename} -- {exc}")
            LOGGER.error(f"后台处理失败: {filename} -- {exc}")
        finally:
            LOGGER.info(
                f"RAG 单文档解析结束: job_id={job_id}; "
                f"start_at={parse_started_at}; end_at={_now_iso()}; "
                f"耗时={round((time.perf_counter() - parse_started) * 1000, 1)} ms"
            )

    async def process_split_document(
            self,
            *,
            job_id: str,
            parts: List[Tuple[str, bytes]],
    ) -> None:
        """分片文档批量处理流程（子文档转换 → 合并 → 后处理管道）。

        无论以何种路径退出（成功/取消/失败/异常）, finally 统一清理输出
        目录下残留的子文档产物目录（<job_id>_part_*）: 成功路径在合并
        阶段已逐个清理, 此处仅兜底扫描; 合并前被取消/中断时若不清理,
        这些目录会永久残留（前端清除只传递主产物目录, 看不到它们）。
        """
        split_started = time.perf_counter()
        split_started_at = _now_iso()
        LOGGER.info(
            f"RAG 分片文档解析开始: job_id={job_id}; start_at={split_started_at}; "
            f"分片数={len(parts)}"
        )
        try:
            await self._process_split_document_inner(job_id=job_id, parts=parts)
        finally:
            self._cleanup_part_dirs(job_id)
            LOGGER.info(
                f"RAG 分片文档解析结束: job_id={job_id}; "
                f"end_at={_now_iso()}; "
                f"耗时={round((time.perf_counter() - split_started) * 1000, 1)} ms"
            )

    @staticmethod
    def _cleanup_part_dirs(job_id: str) -> None:
        """尽力清理输出目录下该文档的子文档产物目录（<job_id>_part_*）。

        分片流程中每个子文档的转换产物落盘为 RAG_OUTPUT_DIR/<job_id>_part_NN,
        成功合并后会逐个删除; 取消/失败/进程中断时由本兜底扫描回收。
        清理失败仅告警——删除文档时服务侧还会按 job_id 再回收一次。
        """
        try:
            base = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR)
            for part_dir in base.glob(f"{job_id}_part_*"):
                if part_dir.is_dir():
                    shutil.rmtree(part_dir, ignore_errors=True)
        except Exception as e:
            LOGGER.warning(f"清理子文档产物目录失败（{job_id}）: {e}")

    async def _process_split_document_inner(
            self,
            *,
            job_id: str,
            parts: List[Tuple[str, bytes]],
    ) -> None:
        """process_split_document 的实际执行体。

        流程:
            1. 全部子文档经 docling convert_all 共享同一份流水线模型转换
               （模型只加载一次; 文档级线程数 = MAX_PARALLEL_PARSE_DOCLING）
            2. 每完成一个子文档, 封装层在转换线程回调, 经 call_soon_threadsafe
               转发到事件循环侧写回进度（completed_parts / history）
            3. 全部子文档完成后按序合并 markdown
            4. 执行解析后处理管道（侧车 → 术语 → 多模态 → 分块 → 嵌入）

        注: docling 单文档转换不可打断, 取消在**当前子文档转换结束后**生效
        （每个子文档开始前有取消检查点, 剩余子文档直接跳过）。
        """
        service = self.document_service

        start_time = time.time()

        doc = await service.get_document_entry(job_id)
        if not doc:
            return

        ocr_options = {
            "do_ocr": doc.get("do_ocr", True),
            "force_ocr": doc.get("force_ocr", False),
        }

        doc["parse_start_time"] = service.now_time()
        doc["status"] = "parsing"
        total_parts = len(parts)
        doc["total_parts"] = total_parts
        doc["completed_parts"] = 0
        doc = await self._save(doc)
        await service.add_history(
            f"开始处理: {doc['filename']}"
            f" ({doc.get('page_count', '?')} 页, {total_parts} 个子文档)"
        )
        LOGGER.info(f"开始分片处理: {doc['filename']} ({total_parts} 个子文档, {doc.get('page_count', '?')} 页)")

        # ---- 批量转换: 每子文档独立 converter（用后即释, 内存不累积） ----
        # 并行槽位数由 MAX_PARALLEL_PARSE_DOCLING 控制（1 = 顺序最稳;
        # 每槽位内存有界, 峰值 ≈ 槽位数 × 3~4GB, 并行不再引发累积型 OOM）。
        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[Tuple[int, str, Optional[Exception]]] = asyncio.Queue()

        def _on_part_converted(idx: int, part_name: str, error: Optional[Exception]) -> None:
            # 转换线程 → 事件循环线程: doc 状态写回统一在事件循环侧, 与既有模型一致
            loop.call_soon_threadsafe(progress_queue.put_nowait, (idx, part_name, error))

        await service.add_history(f"开始解析: {doc['filename']} ({total_parts} 个子文档)")
        convert_task = asyncio.create_task(
            convert_pdfs_to_bundles(
                parts,
                [f"{job_id}_part_{idx:02d}" for idx in range(total_parts)],
                batch_concurrency=PROJECT_CONFIG.MAX_PARALLEL_PARSE_DOCLING,
                on_part_converted=_on_part_converted,
                # 同步检查点（docling 聚合线程调用）: 只读内存取消标记
                should_cancel=lambda: self.is_cancelled_cached(job_id),
                **ocr_options,
            )
        )

        # 逐条消费进度事件（封装层保证每个 part 恰好一条, 不会死等）;
        # 等待期间每 5 秒刷新一次取消标记——长 part 转换期间没有心跳写回,
        # 而 should_cancel 只读内存标记, 需周期查库维持取消时效性
        async def _consume_progress() -> None:
            for _ in range(total_parts):
                while True:
                    try:
                        idx, part_name, error = await asyncio.wait_for(progress_queue.get(), timeout=5.0)
                        break
                    except asyncio.TimeoutError:
                        await self.refresh_cancel_state(job_id)
                if error is None:
                    current = await service.get_document_entry(job_id)
                    if current:
                        # 字段级更新递增进度（浅合并 + 心跳, 不触碰其他进程写入的字段）
                        await self._update(
                            job_id,
                            {"completed_parts": current.get("completed_parts", 0) + 1},
                        )
                    await service.add_history(f"子文档完成 [{idx + 1}/{total_parts}]: {part_name}")
                elif isinstance(error, ConversionCancelledError):
                    # 类型化取消判定: 不再依赖错误文案字符串比对
                    await service.add_history(f"子文档跳过 [{idx + 1}/{total_parts}]: {part_name}（任务已取消）")
                else:
                    await service.add_history(f"子文档失败 [{idx + 1}/{total_parts}]: {part_name} -- {error}")

        # 竞速消费: 转换协程若整体抛异常（封装层致命错误等）, 提前结束等待并上抛,
        # 而不是死等到 Celery time_limit（1 小时）才被强杀
        consumer = asyncio.create_task(_consume_progress())
        await asyncio.wait({consumer, convert_task}, return_when=asyncio.FIRST_EXCEPTION)
        if convert_task.done() and convert_task.exception() is not None:
            consumer.cancel()
            raise convert_task.exception()
        await consumer
        bundles = convert_task.result()

        # 重新加载最新文档状态: 上方进度循环以"新读新写"方式递增 completed_parts,
        # 而本协程持有的 doc 仍是开场快照（completed_parts=0）; 不重载则后续
        # 合并/失败保存会把计数回退为 0（前端 2/2 → 0/2 回跳的根因）。
        doc = await service.get_document_entry(job_id) or doc

        # ---- 组装 completed_results（保持既有结构, 下游合并逻辑不变） ----
        completed_results: List[Optional[Dict[str, Any]]] = []
        for idx, item in enumerate(bundles):
            if isinstance(item, Exception) or item is None:
                completed_results.append({
                    "error": item if isinstance(item, Exception)
                    else RuntimeError("子文档转换结果为空")
                })
            else:
                completed_results.append({
                    "filename": parts[idx][0],
                    "stem": Path(parts[idx][0]).stem,
                    "bundle": item,
                })

        # ---- 取消检查 ----
        if await self.refresh_cancel_state(job_id):
            await service.add_history(f"已取消: {doc['filename']}")
            return

        # ---- 失败检查 ----
        for i, result in enumerate(completed_results):
            if isinstance(result, dict) and "error" in result:
                doc["status"] = "failed"
                doc["summary"] = f"子文档 [{i + 1}/{total_parts}] 失败: {result['error']}"
                doc["updated_at"] = service.now_time()
                doc = await self._save(doc)
                await service.add_history(f"失败: {doc['filename']} -- {doc['summary']}")
                return
            if result is None:
                doc["status"] = "failed"
                doc["summary"] = f"子文档 [{i + 1}/{total_parts}] 结果为空"
                doc["updated_at"] = service.now_time()
                doc = await self._save(doc)
                return

        # ---- 按序合并子文档 markdown ----
        valid_results = [r for r in completed_results if r is not None]
        await service.add_history(f"合并 {len(valid_results)} 个子文档: {doc['filename']}")

        merged_markdown_parts: List[str] = []
        docling_documents: List[Dict[str, Any]] = []
        total_content_length = 0
        # 合并产物目录以文档 job_id 命名（与接口访问键一致）
        final_bundle_dir = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR) / job_id
        final_artifacts_dir = final_bundle_dir / "artifacts"
        for i, result in enumerate(valid_results):
            # 子文档产物目录按 job_id 分片命名, 合并后清理
            bundle = result["bundle"]
            merged_markdown_parts.append(bundle.markdown)
            total_content_length += len(bundle.markdown)
            if bundle.docling_document:
                docling_documents.append(bundle.docling_document)
            # 清理前收集各子文档的 artifacts
            if bundle.artifacts_dir and bundle.artifacts_dir.is_dir():
                final_artifacts_dir.mkdir(parents=True, exist_ok=True)
                for item in bundle.artifacts_dir.iterdir():
                    dst = final_artifacts_dir / item.name
                    if not dst.exists():
                        if item.is_dir():
                            shutil.copytree(item, dst)
                        else:
                            shutil.copy2(item, dst)
            # 提取内容后清理子文档独立目录
            try:
                if bundle.bundle_dir.exists():
                    shutil.rmtree(bundle.bundle_dir, ignore_errors=True)
            except Exception:
                pass

        merged_markdown = "\n\n".join(merged_markdown_parts)
        doc["markdown"] = merged_markdown
        doc["content_length"] = total_content_length
        doc["summary"] = merged_markdown.replace("\n", " ")[:15].strip() or "-"
        doc["updated_at"] = service.now_time()
        doc["parse_end_time"] = service.now_time()
        doc["parse_duration"] = round(time.time() - start_time, 1)
        if final_artifacts_dir.is_dir():
            doc["artifacts_file"] = str(final_artifacts_dir)
        doc = await self._save(doc)
        await service.add_history(f"合并完成: {doc['filename']} ({total_content_length:,} 字符)")

        # ---- 由合并后的 docling 文档构建侧车文件 ----
        if docling_documents:
            try:
                from applications.jiayueyang.rag.sidecar import merge_docling_documents, write_sidecar

                merged_doc = merge_docling_documents(docling_documents)
                bundle_dir = Path(doc.get("output_path") or str(final_bundle_dir))
                bundle_dir.mkdir(parents=True, exist_ok=True)

                merged_json_path = bundle_dir / f"{Path(doc['filename']).stem}.json"
                merged_json_path.write_text(
                    json.dumps(merged_doc, ensure_ascii=False, indent=2), encoding="utf-8"
                )

                sidecar = write_sidecar(
                    str(merged_json_path),
                    str(bundle_dir),
                    engine="docling",
                )
                doc["sidecar"] = sidecar
                doc["output_path"] = str(bundle_dir.resolve())
                await service.add_history(f"侧车文件已生成: {doc['filename']}")
            except Exception as sidecar_err:
                await service.add_history(
                    f"侧车文件生成失败: {type(sidecar_err).__name__}: {sidecar_err}"
                )
                await service.add_history(f"堆栈: {traceback.format_exc()[-300:]}")
                doc["sidecar"] = {}

        # ---- 对合并后的 markdown 执行后处理管道 ----
        await self._run_post_parse_pipeline(
            doc=doc,
            job_id=job_id,
            markdown=merged_markdown,
            enable_vlm=doc.get("enable_vlm", False),
            start_time=start_time,
        )

    # ==================== 中断阶段续跑 ====================

    async def _resume_post_parse_pipeline(self, *, job_id: str) -> None:
        """续跑后处理管道: 跳过内容解析, 从首个未完成阶段恢复执行。

        由 retry_document 标记 resume 且产物完整性校验通过后触发:
        清洗后的 markdown 取自磁盘产物, 侧车取自文档记录, 不重新调用
        docling。_run_post_parse_pipeline 各阶段按产物存在性跳过已完成
        阶段（术语表/多模态分析/分块/向量产物）, 例如:
        - 术语提取中断 → 从术语提取恢复;
        - 向量嵌入中断 → 从嵌入恢复（不重跑解析与分块）;
        - 嵌入成功但写向量库失败 → 加载已有向量直接入库。
        """
        service = self.document_service
        doc = await service.get_document_entry(job_id)
        if not doc:
            return
        filename = doc["filename"]
        bundle_dir = Path(doc.get("output_path") or "")
        md_path = bundle_dir / f"{Path(filename).stem}.md"
        if not md_path.is_file():
            # 理论上不可达（入口已校验产物完整）; 防御性兜底: 清 resume
            # 标记, 下次重试自动降级为全量重跑
            doc["status"] = "failed"
            doc["summary"] = "续跑失败: 清洗后 markdown 产物缺失, 请再次重试（将自动改为全量重跑）"
            doc["resume"] = False
            doc["updated_at"] = service.now_time()
            await self._save(doc)
            return

        start_time = time.time()
        doc["status"] = "terminology"
        doc["updated_at"] = service.now_time()
        doc = await self._save(doc)
        await service.add_history(f"从中断阶段续跑（跳过内容解析）: {filename}")
        try:
            markdown = md_path.read_text(encoding="utf-8")
            await self._run_post_parse_pipeline(
                doc=doc,
                job_id=job_id,
                markdown=markdown,
                enable_vlm=doc.get("enable_vlm", False),
                start_time=start_time,
                is_resume=True,
            )
        except Exception as exc:
            doc["status"] = "failed"
            doc["summary"] = f"{type(exc).__name__}: {exc}"
            doc["error_trace"] = traceback.format_exc()[-500:]
            doc["updated_at"] = service.now_time()
            doc = await self._save(doc)
            await service.add_history(f"续跑失败: {filename} -- {exc}")
            LOGGER.error(f"续跑后处理管道失败: {filename} -- {exc}")

    # ==================== 共享后处理管道 ====================

    async def _run_post_parse_pipeline(
            self,
            *,
            doc: Dict[str, Any],
            job_id: str,
            markdown: str,
            enable_vlm: bool,
            start_time: float,
            is_resume: bool = False,
    ) -> None:
        """解析后共享管道: 术语抽取 → 多模态分析 → 分块 → 向量嵌入。

        单文档流程与分片文档流程共用本管道; 每个阶段前执行取消检查。

        :param is_resume: 续跑模式（内容解析已在上一轮完成）。为 True 时不覆写
            parse_end_time（沿用上一轮解析计时）, 保持解析阶段计时完整。
        """
        service = self.document_service
        filename = doc["filename"]

        # 准备输出目录（以 job_id 命名）
        bundle_dir = Path(doc.get("output_path") or str(Path(PROJECT_CONFIG.RAG_OUTPUT_DIR) / job_id))
        bundle_dir.mkdir(parents=True, exist_ok=True)
        doc["output_path"] = str(bundle_dir.resolve())

        # prev 归档探测（增量更新）: 归档由 submit_update 的归档事务生成, 存在即
        # 说明本次是更新重处理——启用快速通道②、向量复用与更新历史统计
        prev_dir = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR) / f"{job_id}{PREV_SUFFIX}"
        prev_existed = prev_dir.is_dir()
        # 向量复用统计（增量更新）: 成功收尾时写入 update_history;
        # None = 不可知（续跑场景"向量产物已存在"且非快速通道②复制）
        emb_reused: Optional[int] = None
        emb_new: Optional[int] = None

        # 解析后清洗: 目录（TOC）/ 图片引用等无用内容（纯正则, 不依赖 LLM）,
        # 避免污染后续术语提取与分块嵌入
        from common.md_cleanup import clean_markdown
        markdown = clean_markdown(markdown)

        # 清洗后的 markdown 落盘, 并把文档状态同步为清洗后的口径
        md_path = bundle_dir / f"{Path(filename).stem}.md"
        md_path.write_text(markdown, encoding="utf-8")
        doc["content_length"] = len(markdown)
        doc["summary"] = markdown.replace("\n", " ")[:15].strip() or "-"

        sidecar = doc.get("sidecar") or {}

        # ---- 快速通道②（增量更新）: 解析产物与上一版本逐字节一致时, 把 prev 的
        # 后处理产物复制回来, 下游各阶段按各自的"产物已存在"检查自然跳过 ——
        # 一份未变的文档重处理从"全流水线"降为"比对 + 复制"
        if prev_existed:
            await self._try_reuse_prev_artifacts(
                job_id=job_id,
                bundle_dir=bundle_dir,
                prev_dir=prev_dir,
                filename=filename,
                sidecar=sidecar,
                service=service,
            )

        # 正常模式: 清洗完成后刷新 parse_end_time 为"解析+清洗"完成时刻;
        # 续跑模式: 内容解析已在上一轮完成并计时, 保留原值不覆写
        if not is_resume:
            doc["parse_end_time"] = service.now_time()

        # ---- 阶段 1.5: 自动生成术语对照表（产物已存在则跳过——续跑场景）----
        if await self.refresh_cancel_state(job_id):
            await service.add_history(f"检测到任务已取消, 停止处理: {filename}")
            return
        doc["status"] = "terminology"
        doc["updated_at"] = service.now_time()
        doc = await self._save(doc)
        term_md_file = bundle_dir / "terminology.md"
        term_idx_file = bundle_dir / "terminology_index.json"
        if term_md_file.is_file() and term_idx_file.is_file():
            await service.add_history(f"术语表产物已存在, 跳过术语提取: {filename}")
        else:
            doc["term_start_time"] = service.now_time()
            doc["updated_at"] = doc["term_start_time"]
            doc = await self._save(doc)
            await service.add_history(f"开始术语提取: {filename}")
            try:
                from applications.jiayueyang.rag.terminology import generate_terminology
                doc["terminology_completed_batches"] = 0
                doc["terminology_total_batches"] = 1
                doc = await self._save(doc)

                # 进度落盘节流: 每批完成都会触发回调, 高频时每次落盘都是
                # 一次数据库行级更新。2 秒内只持久化一次, 最后一批强制落盘;
                # 心跳容忍 15 分钟, 该频率下长任务心跳始终新鲜
                last_flush = [0.0]
                term_loop = asyncio.get_running_loop()

                def _on_term_progress(done: int, total: int) -> None:
                    # 同步内存快照（每次都改, 开销可忽略）: 后续阶段的
                    # _save(doc) 会浅合并整份快照, 本地不更新则磁盘上的
                    # 进度计数会被旧值回退（进度条回跳）
                    doc["terminology_completed_batches"] = done
                    doc["terminology_total_batches"] = total
                    now = time.time()
                    if done < total and now - last_flush[0] < 2.0:
                        return  # 节流: 跳过本次落盘（内存快照已是最新）
                    last_flush[0] = now
                    # 走管道心跳入口: 打心跳 + 字段级浅合并 + 续期 job 锁。
                    # 本回调为同步上下文（可能在术语生成的线程/协程内被调）,
                    # 数据库写回是协程, 经 run_coroutine_threadsafe 调度到
                    # 常驻事件循环线程执行（与任务主循环同一 loop）
                    asyncio.run_coroutine_threadsafe(
                        self._update(job_id, {
                            "terminology_completed_batches": done,
                            "terminology_total_batches": total,
                        }),
                        term_loop,
                    )

                term_path = await generate_terminology(
                    markdown, str(bundle_dir),
                    progress_callback=_on_term_progress,
                )
                if term_path:
                    await service.add_history(f"术语对应表已生成: {filename}")
            except Exception as term_err:
                await service.add_history(
                    f"术语表生成失败 (非致命): {type(term_err).__name__}: {term_err}"
                )
            doc["term_end_time"] = service.now_time()

        # ---- 阶段 1.6: 文档摘要（文档级召回索引的数据源, 非致命）----
        # LLM 生成结构化摘要并嵌入, 落盘 summary.json 供查询侧文档摘要索引
        # 读取; 摘要文本升级文档表 summary 字段（原为 markdown 前 15 字符占位）。
        # 产物已存在时直接加载（续跑场景, retry 会把 summary 重置为 "-"）
        if await self.refresh_cancel_state(job_id):
            await service.add_history(f"检测到任务已取消, 停止处理: {filename}")
            return
        summary_file = bundle_dir / "summary.json"
        summary_data = None
        if summary_file.is_file():
            try:
                candidate = json.loads(summary_file.read_text(encoding="utf-8"))
                if candidate.get("summary") and candidate.get("vector"):
                    summary_data = candidate
            except Exception as summary_load_err:
                LOGGER.warning(f"摘要产物不可读, 将重新生成: {summary_load_err}")
        if summary_data is not None:
            doc["summary"] = summary_data["summary"]
            await service.add_history(f"摘要产物已存在, 跳过摘要生成: {filename}")
        else:
            await service.add_history(f"开始生成文档摘要: {filename}")
            try:
                from applications.jiayueyang.rag.doc_summary import generate_doc_summary
                summary_data = await generate_doc_summary(markdown, filename)
                summary_file.write_text(
                    json.dumps(
                        {**summary_data, "created_at": int(time.time())},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                doc["summary"] = summary_data["summary"]
                await service.add_history(f"文档摘要已生成: {filename}")
            except Exception as summary_err:
                # 非致命: 摘要缺失仅使该文档不进入文档级召回索引,
                # 分块级检索不受影响（存量回填脚本可事后补齐）
                summary_data = None
                await service.add_history(
                    f"文档摘要生成失败 (非致命): {type(summary_err).__name__}: {summary_err}"
                )

        # ---- 阶段 2: 多模态分析（仅 VLM 启用时执行） ----
        from applications.jiayueyang.rag.multimodal import analyze_multimodal, build_multimodal_chunks

        if await self.refresh_cancel_state(job_id):
            await service.add_history(f"检测到任务已取消, 停止处理: {filename}")
            return
        if enable_vlm:
            # 分析产物已存在（续跑场景）→ 加载使用, 跳过 VLM 分析;
            # 产物不可读时回退重新分析
            mm_file = bundle_dir / "multimodal_analysis.json"
            mm_result = None
            if mm_file.is_file():
                try:
                    mm_result = json.loads(mm_file.read_text(encoding="utf-8"))
                except Exception as mm_load_err:
                    LOGGER.warning(f"多模态分析产物不可读, 将重新分析: {mm_load_err}")
            if mm_result is not None:
                img_count = len(mm_result.get("image_descriptions", []))
                tbl_count = len(mm_result.get("table_summaries", []))
                doc["analyzing_stage_skipped"] = mm_result.get("analyzing_stage_skipped", False)
                doc = await self._save(doc)
                await service.add_history(
                    f"多模态分析产物已存在, 跳过（图片: {img_count}, 表格: {tbl_count}）: {filename}"
                )
            else:
                doc["status"] = "analyzing"
                analyze_start_t = time.time()
                doc["analyze_start_time"] = service.now_time()
                doc["updated_at"] = doc["analyze_start_time"]
                doc = await self._save(doc)
                await service.add_history(f"开始多模态分析: {filename}")

                mm_result = analyze_multimodal(
                    sidecar.get("drawings", []) if sidecar else [],
                    sidecar.get("tables", []) if sidecar else [],
                    doc.get("artifacts_file", ""),
                    enable_vlm=True,
                )
                img_count = len(mm_result.get("image_descriptions", []))
                tbl_count = len(mm_result.get("table_summaries", []))
                doc["analyze_end_time"] = service.now_time()
                doc["analyze_duration"] = round(time.time() - analyze_start_t, 1)
                doc["analyzing_stage_skipped"] = mm_result.get("analyzing_stage_skipped", False)
                mm_file.write_text(json.dumps(mm_result, ensure_ascii=False, indent=2), encoding="utf-8")
                doc = await self._save(doc)
                await service.add_history(
                    f"多模态分析完成（图片: {img_count}, 表格: {tbl_count}）: {filename}"
                )
        else:
            mm_result = {
                "image_descriptions": [], "table_summaries": [],
                "analyzing_stage_skipped": True, "multimodal_processed": False,
            }
            doc["analyzing_stage_skipped"] = True

        # ---- 阶段 3: 分块（chunks.json 已存在则跳过——续跑场景）----
        if await self.refresh_cancel_state(job_id):
            await service.add_history(f"检测到任务已取消, 停止处理: {filename}")
            return
        chunks_file = bundle_dir / "chunks.json"
        cached_chunks = None
        chunks_changed = False
        if chunks_file.is_file():
            try:
                chunks_dict_cached = json.loads(chunks_file.read_text(encoding="utf-8"))
                cached_chunks = [chunks_dict_cached[k] for k in sorted(chunks_dict_cached)]
            except Exception as chunks_load_err:
                LOGGER.warning(f"分块产物不可读, 将重新分块: {chunks_load_err}")
        if cached_chunks is not None:
            all_chunks = cached_chunks
            # 旧任务的 chunks.json 可能生成于表格行级分块功能上线之前。
            # 缓存命中时也补算派生表格块，避免“已有分块直接跳过”让历史文档
            # 永远缺少 table_row。内容排重保证重复续跑不会反复追加。
            if PROJECT_CONFIG.TABLE_ROW_CHUNKS:
                from applications.jiayueyang.rag.table_rows import (
                    build_code_table_chunks_from_docling_json,
                    build_table_chunks,
                    build_table_chunks_from_markdown,
                    merge_derived_table_chunks,
                )
                derived_table_chunks: List[Dict[str, Any]] = []
                derived_table_chunks.extend(build_table_chunks(
                    sidecar.get("tables"), filename, markdown_text=markdown,
                ))
                derived_table_chunks.extend(build_table_chunks_from_markdown(
                    markdown, sidecar.get("tables"), filename,
                ))
                docling_json_path = md_path.with_suffix(".json")
                derived_table_chunks.extend(build_code_table_chunks_from_docling_json(
                    docling_json_path, filename,
                ))
                appended, replaced = merge_derived_table_chunks(all_chunks, derived_table_chunks)
                if appended or replaced:
                    chunks_changed = True
                    chunks_dict = {f"chunk-{i:04d}": c for i, c in enumerate(all_chunks)}
                    chunks_file.write_text(
                        json.dumps(chunks_dict, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    await service.add_history(
                        f"为历史分块补充表格派生块 {appended} 个, 原位更新 {replaced} 个: {filename}"
                    )
            doc["status"] = "chunking"
            doc["updated_at"] = service.now_time()
            doc["chunks_count"] = len(all_chunks)
            doc["chunks_file"] = str(chunks_file.resolve())
            doc["embed_start_time"] = service.now_time()
            doc = await self._save(doc)
            await service.add_history(f"分块产物已存在, 跳过分块 ({len(all_chunks)} chunks): {filename}")
        else:
            doc["status"] = "chunking"
            doc["chunk_start_time"] = service.now_time()
            doc["updated_at"] = doc["chunk_start_time"]
            doc = await self._save(doc)
            await service.add_history(f"开始分块: {filename}")

            from applications.jiayueyang.rag.chunker import chunk_document
            from applications.jiayueyang.rag.table_rows import strip_markdown_tables

            # 文本分块前去除 markdown pipe-table: 表格数据已由结构化分块
            # 覆盖, 文本块中仅保留占位符（含表格标题 + 行列数）作为上下文
            markdown_for_text = strip_markdown_tables(markdown)
            text_chunks = chunk_document(markdown_for_text)
            # 追加多模态分块（图片/表格描述）
            all_chunks = build_multimodal_chunks(mm_result, text_chunks)

            # 追加表格分块（表级摘要 + 行级块, 与文本块并存入库; TABLE_ROW_CHUNKS 开关）
            table_chunks: List[Dict[str, Any]] = []
            if PROJECT_CONFIG.TABLE_ROW_CHUNKS:
                from applications.jiayueyang.rag.table_rows import (
                    build_code_table_chunks_from_docling_json,
                    build_table_chunks,
                    build_table_chunks_from_markdown,
                )
                # 路径 A: docling 识别的表格（tables.json）;
                # 传入 markdown 文本用于为无 caption 表格从章节标题补名
                table_chunks = build_table_chunks(
                    sidecar.get("tables"), filename, markdown_text=markdown,
                )
                # 路径 B: docling 未识别的 markdown pipe-table（补救漏网表格）
                md_table_chunks = build_table_chunks_from_markdown(
                    markdown, sidecar.get("tables"), filename,
                )
                table_chunks.extend(md_table_chunks)
                # 路径 C: markdown/tables.json 被解析器压平成单列时，从原始
                # Docling JSON 的单元格坐标恢复代码表行。
                table_chunks.extend(build_code_table_chunks_from_docling_json(
                    md_path.with_suffix(".json"), filename,
                ))
                for chunk in table_chunks:
                    chunk["chunk_order_index"] = len(all_chunks)
                    all_chunks.append(chunk)
            # 过滤空内容分块: 空文本只能嵌入为零向量（COSINE 度量下行为
            # 未定义, 成为检索噪声）, 入库无意义——在落盘/嵌入/入库前统一
            # 剔除, 保证 chunks.json / embeddings.json / 向量库三者口径一致
            before_filter = len(all_chunks)
            all_chunks = [c for c in all_chunks if (c.get("content") or "").strip()]
            empty_skipped = before_filter - len(all_chunks)
            if empty_skipped:
                await service.add_history(f"过滤空内容分块 {empty_skipped} 个: {filename}")
            # 分块结果落盘
            chunks_dict = {f"chunk-{i:04d}": c for i, c in enumerate(all_chunks)}
            chunks_file.write_text(json.dumps(chunks_dict, ensure_ascii=False, indent=2), encoding="utf-8")
            doc["chunks_count"] = len(all_chunks)
            doc["chunks_file"] = str(chunks_file.resolve())
            doc["chunk_end_time"] = service.now_time()
            doc["embed_start_time"] = doc["chunk_end_time"]
            doc = await self._save(doc)
            await service.add_history(
                f"分块完成 ({len(all_chunks)} chunks, 含表格块 {len(table_chunks)}): {filename}"
            )

        # ---- 阶段 4: 向量嵌入 ----
        if await self.refresh_cancel_state(job_id):
            await service.add_history(f"检测到任务已取消, 停止处理: {filename}")
            return
        doc["status"] = "embedding"
        doc["updated_at"] = service.now_time()
        doc = await self._save(doc)
        await service.add_history(f"开始向量嵌入: {filename}")

        from applications.jiayueyang.rag.embedding import embed_chunks, save_embeddings
        from applications.jiayueyang.rag.milvus_store import (
            delete_by_doc_id,
            upsert_chunks as store_chunks,
        )

        try:
            # 向量产物已存在（续跑场景: 嵌入成功但入库中断）→ 加载直接
            # 入库, 跳过嵌入; 产物不可读或缺向量时回退重新嵌入
            embeddings_file = bundle_dir / "embeddings.json"
            embedded_chunks = None
            if embeddings_file.is_file() and not chunks_changed:
                try:
                    emb_data = json.loads(embeddings_file.read_text(encoding="utf-8"))
                    candidate = [emb_data[k] for k in sorted(emb_data)]
                    if (
                        candidate
                        and len(candidate) == len(all_chunks)
                        and all(c.get("vector") for c in candidate)
                    ):
                        embedded_chunks = candidate
                except Exception as emb_load_err:
                    LOGGER.warning(f"向量产物不可读, 将重新嵌入: {emb_load_err}")
            if embedded_chunks is not None:
                # 跳过分支（续跑/快速通道②）: 统计补齐——快速通道②整体复制回
                # 的向量产物全部来自 prev; 其余（本轮嵌入中断残留）不可知, 留 None
                if job_id in self._fast2_jobs:
                    emb_reused, emb_new = self._fast2_jobs.pop(job_id), 0
                await service.add_history(
                    f"向量产物已存在, 跳过嵌入（加载 {len(embedded_chunks)} 个向量）: {filename}"
                )
            else:
                # 增量更新向量复用: 以 prev 版本构建内容哈希查找表
                # （SHA256(content) → vector, 与位置无关, 对分块边界漂移不敏感）;
                # meta 守卫不通过（无 meta / 模型或维度与当前配置不符）时
                # 保守回退全量嵌入——跨模型向量复用会造成相似度失真
                prev_cache = self._load_prev_embedding_cache(prev_dir) if prev_existed else None
                if prev_cache is not None:
                    miss_chunks = []
                    for c in all_chunks:
                        key = hashlib.sha256((c.get("content") or "").encode("utf-8")).hexdigest()
                        vec = prev_cache.get(key)
                        if vec is not None and len(vec) == PROJECT_CONFIG.EMBEDDING_DIM:
                            c["vector"] = vec
                        else:
                            miss_chunks.append(c)
                    emb_reused = len(all_chunks) - len(miss_chunks)
                    emb_new = len(miss_chunks)
                    if miss_chunks:
                        await service.add_history(
                            f"向量复用 {emb_reused} / 新嵌入 {emb_new}: {filename}"
                        )
                        await embed_chunks(miss_chunks)
                    else:
                        await service.add_history(
                            f"全部向量命中上一版本缓存（{emb_reused} 个）, 跳过嵌入调用: {filename}"
                        )
                    embedded_chunks = all_chunks
                else:
                    embedded_chunks = await embed_chunks(all_chunks)
                    emb_reused, emb_new = 0, len(all_chunks)
                await save_embeddings(embedded_chunks, str(bundle_dir))
                # 嵌入 meta（模型名 + 维度）: 未来增量更新复用向量的出处守卫,
                # 缺失时复用侧无法证明向量版本, 只能保守全量重嵌
                self._write_embeddings_meta(bundle_dir)
            # 写前预清理（尽力而为）: 块 ID 为 <doc_id>-chunk-NNNN 顺序编号,
            # 若同文档上一次写入过分块更多（重跑/重试时分块数变化）, 尾部
            # 旧块会残留污染检索。先按 doc_id 清旧再写, 使入库集合完全由
            # 本次运行决定。刻意放在嵌入成功之后: 嵌入失败时不得清空旧向量
            try:
                delete_by_doc_id(job_id)
            except Exception as purge_err:
                LOGGER.warning(
                    f"写前清理旧向量失败（不影响本次写入, upsert 幂等覆盖）: "
                    f"job_id={job_id}, {purge_err}"
                )
            store_chunks(embedded_chunks, file_path=doc.get("filename", ""), doc_id=job_id)
            # 增量更新成功收尾: 新版本向量已在服务 → 删除 prev 归档（旧版本不再
            # 需要）, 清除"更新中"标记并记录本次更新统计（复用/新嵌入块数）
            if prev_existed:
                self._remove_prev_archives(job_id)
                doc["is_updating"] = False
                update_history = list(doc.get("update_history") or [])
                update_history.append({
                    "time": service.now_time(),
                    "filename": filename,
                    "reused": emb_reused,
                    "embedded": emb_new,
                })
                doc["update_history"] = update_history
            doc["embed_end_time"] = service.now_time()
            doc["process_end_time"] = doc["embed_end_time"]
            doc["status"] = "complete"
            doc["resume"] = False  # 续跑标记在完成后清除
            doc["updated_at"] = doc["embed_end_time"]
            doc = await self._save(doc)
            await service.add_history(
                f"向量嵌入完成"
                f"（{len(embedded_chunks)} 个向量已写入 Milvus）: {filename}"
            )
            if prev_existed and emb_reused is not None:
                await service.add_history(
                    f"增量更新完成（复用 {emb_reused} / 新嵌入 {emb_new}）: {filename}"
                )
        except Exception as exc:
            doc["status"] = "failed"
            doc["summary"] = f"{type(exc).__name__}: {exc}"
            doc["error_trace"] = traceback.format_exc()[-500:]
            doc["updated_at"] = service.now_time()
            doc = await self._save(doc)
            await service.add_history(f"嵌入失败: {filename} -- {exc}")
            LOGGER.error(f"向量嵌入失败: {filename} -- {exc}")
            return

    # ==================== 增量更新: 产物比对与向量复用 ====================

    async def _try_reuse_prev_artifacts(
            self,
            *,
            job_id: str,
            bundle_dir: Path,
            prev_dir: Path,
            filename: str,
            sidecar: Dict[str, Any],
            service: RagDocumentService,
    ) -> None:
        """快速通道②: 解析产物与上一版本逐字节一致 → 复制回 prev 的后处理产物。

        比对基线 = 下游各阶段的全部直接输入: 清洗后 markdown + 侧车四元组
        + artifacts 目录（VLM 的图片输入）。任一差异（含 prev 缺文件）即放弃
        复用, 走正常重处理。一致时把 prev 的后处理产物逐个复制回本目录,
        术语/摘要/多模态/分块阶段按各自的"产物已存在"检查自然跳过;
        embeddings.json 仅在 meta 守卫通过（模型/维度与当前配置一致）时复制,
        否则留给阶段 4 走内容哈希复用（只嵌变化块）。

        内容未变的文档重处理由此从"全流水线（含 LLM 与嵌入调用）"降为
        "哈希比对 + 同盘复制"。
        """
        stem = Path(filename).stem

        def _file_hash(path: Path) -> Optional[str]:
            try:
                if path.is_file():
                    return hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                pass
            return None

        def _dir_hashes(base: Path) -> Dict[str, str]:
            hashes: Dict[str, str] = {}
            if base.is_dir():
                for p in sorted(base.rglob("*")):
                    if p.is_file():
                        try:
                            hashes[p.relative_to(base).as_posix()] = hashlib.sha256(
                                p.read_bytes()
                            ).hexdigest()
                        except OSError:
                            return {}  # 读取失败 → 视为不一致, 放弃复用
            return hashes

        # ---- 当前版本的比对基线（md + 侧车四元组, 按文件名对齐 prev）----
        sidecar_names: List[str] = []
        cur_hashes: Dict[str, Optional[str]] = {f"{stem}.md": _file_hash(bundle_dir / f"{stem}.md")}
        for key in ("meta", "blocks", "drawings", "tables"):
            path_str = str(sidecar.get(key) or "")
            if path_str:
                name = Path(path_str).name
                sidecar_names.append(name)
                cur_hashes[name] = _file_hash(Path(path_str))
        if cur_hashes.get(f"{stem}.md") is None:
            return  # 清洗后 md 缺失（异常场景）, 无从比对

        prev_hashes: Dict[str, Optional[str]] = {
            name: _file_hash(prev_dir / name) for name in cur_hashes
        }
        artifacts_same = _dir_hashes(bundle_dir / "artifacts") == _dir_hashes(prev_dir / "artifacts")
        if cur_hashes != prev_hashes or not artifacts_same:
            await service.add_history(f"解析产物与上一版本存在差异, 执行完整重处理: {filename}")
            return

        # ---- 逐字节一致: 复制回后处理产物 ----
        copied: List[str] = []
        for name in self._REUSABLE_ARTIFACTS:
            src = prev_dir / name
            if src.is_file():
                try:
                    shutil.copy2(src, bundle_dir / name)
                    copied.append(name)
                except OSError as e:
                    # 复制失败 → 该产物按缺失处理（对应阶段正常重跑）, 不致命
                    LOGGER.warning(f"prev 产物复制失败（{name}）, 该阶段将重跑: {e}")
        emb_copied = False
        if self._prev_meta_matches(prev_dir):
            for name in ("embeddings.json", "embeddings_meta.json"):
                src = prev_dir / name
                if src.is_file():
                    try:
                        shutil.copy2(src, bundle_dir / name)
                        emb_copied = emb_copied or name == "embeddings.json"
                    except OSError as e:
                        LOGGER.warning(f"prev 向量产物复制失败, 阶段 4 将走内容哈希复用: {e}")
        if emb_copied:
            try:
                count = len(json.loads((bundle_dir / "embeddings.json").read_text(encoding="utf-8")))
            except Exception:
                count = 0
            self._fast2_jobs[job_id] = count
        await service.add_history(
            f"解析产物与上一版本一致, 复用后处理产物 {len(copied)} 项"
            f"{'（含向量）' if emb_copied else ''}: {filename}"
        )
        LOGGER.info(f"增量更新快速通道②命中: {filename} (job_id={job_id}, 复制产物 {len(copied)} 项)")

    @staticmethod
    def _prev_meta_matches(prev_dir: Path) -> bool:
        """prev 的 embeddings_meta.json 是否证明其向量出自当前配置的模型/维度。

        meta 缺失（存量产物或未写 meta 的旧版本）→ 无法证明出处 → False,
        复用侧保守回退（全量重嵌或内容哈希复用前同样校验）。
        """
        meta_file = prev_dir / "embeddings_meta.json"
        if not meta_file.is_file():
            return False
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            return False
        return (
            meta.get("model") == PROJECT_CONFIG.EMBEDDING_MODEL
            and int(meta.get("dim") or 0) == int(PROJECT_CONFIG.EMBEDDING_DIM)
        )

    @staticmethod
    def _load_prev_embedding_cache(prev_dir: Path) -> Optional[Dict[str, List[float]]]:
        """构建 prev 版本向量复用缓存: SHA256(content) → vector（与位置无关）。

        位置无关是关键: 分块边界漂移（如段落增删导致后续块整体平移）时,
        内容未变的块仍能命中缓存, 只嵌真正新增/变化的块。

        守卫: meta 缺失或与当前 EMBEDDING_MODEL/EMBEDDING_DIM 不符 → None
        （跨模型向量不可复用, 相似度失真）; 大文件加载失败同样回退全量嵌入。
        """
        prev_emb = prev_dir / "embeddings.json"
        if not prev_emb.is_file():
            return None
        if not RagPipelineService._prev_meta_matches(prev_dir):
            return None
        try:
            data = json.loads(prev_emb.read_text(encoding="utf-8"))
        except Exception as e:
            LOGGER.warning(f"prev 向量产物不可读, 回退全量嵌入: {e}")
            return None
        cache: Dict[str, List[float]] = {}
        for c in data.values():
            c = c or {}
            content = c.get("content") or ""
            vec = c.get("vector")
            if content and vec:
                cache[hashlib.sha256(content.encode("utf-8")).hexdigest()] = vec
        del data  # 向量引用已转入 cache, 释放其余解析对象（content 字符串等）
        return cache

    @staticmethod
    def _write_embeddings_meta(bundle_dir: Path) -> None:
        """写入嵌入 meta（模型名 + 维度）: 未来增量更新向量复用的模型漂移守卫。

        与 embeddings.json 同目录同生命周期; 嵌入模型/维度变更后, 旧 meta
        与新配置不符 → 复用守卫自动失效, 不会误用旧模型向量。
        """
        try:
            (bundle_dir / "embeddings_meta.json").write_text(
                json.dumps(
                    {
                        "model": PROJECT_CONFIG.EMBEDDING_MODEL,
                        "dim": PROJECT_CONFIG.EMBEDDING_DIM,
                        "created_at": int(time.time()),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as e:
            LOGGER.warning(f"嵌入 meta 写入失败（{bundle_dir}）: {e}")
