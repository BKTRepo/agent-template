# -*- coding: utf-8 -*-
"""原生 docling 离线文档解析封装（替代 docling-serve 远程服务）。

基于 docling 官方高级 API ``DocumentConverter``:
- 离线模式: 检测到 ``DOCLING_OFFLINE_DIR/docling/models`` 时启用本地模型
  （artifacts_path）并设置 HuggingFace 离线环境变量, 全程不联网;
- 转换在独立线程中执行（docling 为同步阻塞 API）, 不阻塞事件循环;
- 转换器"按次新建、用后即弃": docling-parse C++ 后端与 onnxruntime 会在
  转换器实例内累积内存（页面缓存 / ORT arena）且不随单次转换释放,
  复用转换器会让内存跨文档单调上涨直至 std::bad_alloc（32GB 机器亦可触发,
  见 docling 官方 FAQ）; 每次转换新建 converter、结束后 del + gc 释放,
  以每子文档约 5 秒的模型重载时间换取内存不累积;
- 产物落盘结构与原 docling-serve 流程保持一致（BundleResult）。
"""
import asyncio
import gc
import io
import json
import multiprocessing
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from common.docling_bundle import BundleResult
from configure import LOGGER, PROJECT_CONFIG

# Windows 上 torch.compile(inductor) 需要 MSVC 编译器(cl.exe), 未安装时布局模型
# (transformers 后端)初始化会报 "Compiler: cl is not found"; 关闭 dynamo 编译即可,
# 仅损失推理优化、不影响解析结果。须在 docling 导入 torch 之前设置。
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")


class ConversionCancelledError(RuntimeError):
    """子文档转换因任务取消而跳过。

    类型化取消信号: 调用方应以 ``isinstance`` 判断取消, 不做字符串比对,
    文案调整不会静默破坏取消识别逻辑。
    """


# 取消错误的统一文案（跨进程模式经 pickle 传字符串, 父进程据此重建类型化异常）
_CANCEL_MESSAGE = "任务已被取消, 停止后续子文档解析"


def _terminate_owned_pool(executor: Any) -> None:
    """仅停止本次转换创建的解析进程，不触碰 Celery 或其他文档。

    Python 3.12/3.13 的 Executor 尚无 terminate_workers()，因此在
    shutdown 前保存其拥有的 Process 对象并逐个回收。
    """
    processes = list((getattr(executor, "_processes", None) or {}).values())
    for process in processes:
        if process.is_alive():
            process.terminate()
    deadline = time.monotonic() + 2.0
    for process in processes:
        process.join(timeout=max(0.0, deadline - time.monotonic()))
    for process in processes:
        if process.is_alive():
            process.kill()
    for process in processes:
        process.join(timeout=2.0)



def _artifacts_path() -> Optional[Path]:
    """解析离线模型目录（docling_offline/docling/models）。"""
    models_dir = Path(PROJECT_CONFIG.DOCLING_OFFLINE_DIR) / "docling" / "models"
    if models_dir.is_dir():
        return models_dir
    return None


def _enable_offline_env() -> None:
    """设置 HuggingFace 离线环境变量, 禁止运行时联网拉取模型。"""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"


def _build_ocr_options(force_ocr: bool) -> Any:
    """构建 OCR 选项: 统一使用 RapidOCR（onnxruntime 后端, 离线轻量无需 torch）。"""
    from docling.datamodel.pipeline_options import RapidOcrOptions

    ocr_options = RapidOcrOptions()
    ocr_options.force_full_page_ocr = bool(force_ocr)
    return ocr_options


def _build_pipeline_options(do_ocr: bool, force_ocr: bool) -> Any:
    """构建 PDF 流水线选项（离线模型 + OCR + 表格/图片功能开关）。"""
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    options = PdfPipelineOptions()

    # OCR 配置
    options.do_ocr = bool(do_ocr)
    if options.do_ocr:
        options.ocr_options = _build_ocr_options(force_ocr)

    # 功能开关（来自项目配置）
    options.do_table_structure = PROJECT_CONFIG.DOCLING_TABLE_STRUCTURE
    options.do_formula_enrichment = PROJECT_CONFIG.DOCLING_FORMULA_ENRICHMENT
    options.do_picture_classification = PROJECT_CONFIG.DOCLING_PICTURE_CLASSIFICATION
    options.do_picture_description = PROJECT_CONFIG.DOCLING_PICTURE_DESCRIPTION

    # 生成图片产物（供侧车文件与多模态分析消费）
    options.generate_picture_images = True
    options.images_scale = 2.0

    # 内存控制（docling 官方 std::bad_alloc FAQ 推荐）:
    # 不生成整页图片（侧车/多模态仅消费 picture 产物）; 各阶段按单页批次执行,
    # 压低流水线内并发页缓冲的内存峰值
    options.generate_page_images = False
    options.ocr_batch_size = 1
    options.layout_batch_size = 1
    options.table_batch_size = 1

    # 加速设备: true = CUDA（需 CUDA 版 torch）, false = 纯 CPU
    from docling.datamodel.accelerator_options import (
        AcceleratorDevice,
        AcceleratorOptions,
    )

    use_gpu = PROJECT_CONFIG.DOCLING_USE_GPU
    options.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CUDA if use_gpu else AcceleratorDevice.CPU
    )
    LOGGER.info(f"【docling】加速设备: {'cuda' if use_gpu else 'cpu'}")

    # 离线模型
    artifacts = _artifacts_path()
    if artifacts is not None:
        _enable_offline_env()
        options.artifacts_path = str(artifacts)
        LOGGER.info(f"【docling】启用离线模型: {artifacts}")
    else:
        LOGGER.warning("【docling】未检测到离线模型目录, 将使用 docling 默认模式（首次使用会联网下载模型）")

    return options


def _create_converter(do_ocr: bool, force_ocr: bool) -> Any:
    """新建 DocumentConverter（构建器; 复用策略由 ``_get_process_converter`` 管理）。

    后端由 ``DOCLING_PDF_BACKEND`` 决定: ``pypdfium2``（默认, 内存高效,
    docling 官方对大型/复杂 PDF 的推荐选项, 无跨调用累积 → 进程内缓存复用）/
    ``docling_parse``（表格质量更高, 但存在官方 FAQ 所述的跨调用内存累积 →
    每次新建、用后释放）。

    注: 逐任务重建模型会让 docling 阶段线程各自持有整套模型引用, GPU 下
    显存随转换次数泄漏式上涨; 故 pypdfium2 模式下选择进程内复用,
    worker 跨任务复用至批次结束（子进程不回收重生, 见 _run_pool 注释）。
    """
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = _build_pipeline_options(do_ocr, force_ocr)
    format_kwargs: Dict[str, Any] = {"pipeline_options": pipeline_options}
    if (PROJECT_CONFIG.DOCLING_PDF_BACKEND or "pypdfium2").strip().lower() == "pypdfium2":
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

        format_kwargs["backend"] = PyPdfiumDocumentBackend
    # 其他取值 → backend 缺省, 使用 docling 默认的 docling_parse 后端
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(**format_kwargs),
        }
    )


def _materialize_bundle(
        result: Any,
        bundle_dir: Path,
        stem: str,
        picture_name_prefix: str = "",
) -> BundleResult:
    """将转换结果落盘为产物包（md + json + artifacts）。

    图片写入 ``artifacts/picture-{prefix}XXXX.png`` 并把 JSON 中的 URI 改写为
    相对路径, 供侧车文件（drawings.path）与多模态分析按 ``artifacts_dir/文件名``
    定位; Markdown 以 REFERENCED 模式导出, 图片在正文对应位置输出为
    ``![Image](artifacts/...)`` 引用（默认为不可见占位注释, 前端无法渲染）。

    picture_name_prefix: 分片流程传入分片编号前缀（如 "00-"），避免各分片
    图片同名、合并到最终 artifacts 目录时互相覆盖。
    """
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # 持久化图片产物
    artifacts_dir: Optional[Path] = None
    for i, pic in enumerate(result.document.pictures):
        image = getattr(pic, "image", None)
        pil_image = getattr(image, "pil_image", None) if image is not None else None
        if pil_image is not None:
            if artifacts_dir is None:
                artifacts_dir = bundle_dir / "artifacts"
                artifacts_dir.mkdir(parents=True, exist_ok=True)
            rel_name = f"picture-{picture_name_prefix}{i:04d}.png"
            pil_image.save(str(artifacts_dir / rel_name), format="PNG")
            image.uri = f"artifacts/{rel_name}"

    # Markdown 全文（REFERENCED: 图片输出为 ![Image](artifacts/...) 可见引用）
    from docling_core.types.doc import ImageRefMode

    markdown = result.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED)
    md_path = bundle_dir / f"{stem}.md"
    md_path.write_text(markdown, encoding="utf-8")

    # DoclingDocument 结构化 JSON（侧车与合并流程消费）
    doc_dict = result.document.export_to_dict()
    json_path = bundle_dir / f"{stem}.json"
    json_path.write_text(json.dumps(doc_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    return BundleResult(
        bundle_dir=bundle_dir,
        json_path=json_path,
        md_path=md_path,
        artifacts_dir=artifacts_dir,
        markdown=markdown,
        docling_document=doc_dict,
    )


async def convert_pdf_to_bundle(
        file_bytes: bytes,
        filename: str,
        bundle_name: str,
        *,
        do_ocr: bool = True,
        force_ocr: bool = True,
        should_cancel: Optional[Callable[[], bool]] = None,
) -> BundleResult:
    """将 PDF 字节流转换为产物包（目录以 bundle_name 命名, 通常为 job_id）。

    转换前清空同名目录；原生解析在独立子进程执行，取消时可单独回收。
    """
    # 单文件也放入可回收的独立进程，删除不再等待不可中断的原生调用。
    results = await convert_pdfs_to_bundles(
        [(filename, file_bytes)], [bundle_name], do_ocr=do_ocr,
        force_ocr=force_ocr, should_cancel=should_cancel,
    )
    if isinstance(results[0], Exception):
        raise results[0]
    return results[0]


def _fire_part_callback(
        callback: Optional[Callable[[int, str, Optional[Exception]], None]],
        idx: int,
        filename: str,
        error: Optional[Exception],
) -> None:
    """触发子文档完成回调; 回调异常仅记日志, 不影响转换主流程。"""
    if callback is None:
        return
    try:
        callback(idx, filename, error)
    except Exception as e:
        LOGGER.error(f"【docling】on_part_converted 回调异常: {type(e).__name__}: {e}")


# 进程内 converter 缓存: 进程池模式下每个子进程有独立模块状态, 缓存天然进程隔离。
# 模型在子进程生命周期内只建一次、跨子文档任务复用——避免逐任务重建造成的
# 显存抖动/碎片, 以及 docling 阶段线程持有旧模型引用导致的显存逐次泄漏;
# 批次结束进程池销毁、子进程退出, 兜底清零一切残留。
_PROCESS_CONVERTERS: Dict[Tuple[bool, bool], Any] = {}


def _get_process_converter(
        do_ocr: bool, force_ocr: bool
) -> Tuple[Any, bool]:
    """获取本子进程内复用的 converter。

    返回 ``(converter, dispose_after_use)``。pypdfium2 后端无跨调用累积问题 →
    缓存复用（GPU 显存稳态）; docling_parse 后端存在官方 FAQ 所述的跨调用
    内存累积 → 仍每次新建、用后释放。
    """
    cacheable = (PROJECT_CONFIG.DOCLING_PDF_BACKEND or "").strip().lower() == "pypdfium2"
    key = (bool(do_ocr), bool(force_ocr))
    if cacheable:
        converter = _PROCESS_CONVERTERS.get(key)
        if converter is not None:
            return converter, False
    converter = _create_converter(do_ocr, force_ocr)
    if cacheable:
        _PROCESS_CONVERTERS[key] = converter
        return converter, False
    return converter, True


def _release_after_conversion(converter: Any, dispose: bool) -> None:
    """转换结束后的资源归还: 缓存复用时仅归还临时显存, 非缓存时整体释放。"""
    if dispose:
        del converter
    gc.collect()
    # 归还 torch 预留显存（caching allocator 默认不还给驱动）
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _process_chunk_in_process(
        chunk: List[Tuple[int, str, bytes, str]],
        do_ocr: bool,
        force_ocr: bool,
        rag_output_dir: str,
        cancel_event: Any = None,
) -> List[Tuple[int, Optional[BundleResult], Optional[str], Optional[str]]]:
    """在独立进程中处理一个 PDF 分块（模块级函数, ProcessPoolExecutor 任务体）。

    进程隔离并行模式: 每个进程自建 converter 实例, 进程间状态天然隔离;
    分块内部沿用本模块内存策略——每子文档新建 converter、用后释放。
    跨进程取消经 ``cancel_event``（multiprocessing.Event, 父进程置位）探测。

    参数:
        chunk: [(全局序号, 文件名, PDF 字节, 产物目录名), ...];

    返回:
        每子文档一条记录 ``(idx, BundleResult 或 None, 错误文本 或 None,
        部分失败警告 或 None)``——全部字段可 pickle, 由父进程重建结果并
        触发进度回调（回调不可跨进程传递, 统一留在父进程侧）。
    """
    from docling.datamodel.base_models import ConversionStatus, DocumentStream
    from docling.datamodel.settings import settings as docling_settings

    # 与父进程一致的平台批配置（子进程是全新解释器, 需独立设置）
    docling_settings.perf.page_batch_size = 1

    out_root = Path(rag_output_dir)
    records: List[Tuple[int, Optional[BundleResult], Optional[str], Optional[str]]] = []

    for idx, filename, data, bundle_name in chunk:
        # 取消检查点: 每个子文档开始前探测共享 Event
        if cancel_event is not None and cancel_event.is_set():
            records.append((idx, None, _CANCEL_MESSAGE, None))
            continue

        part_dir = out_root / bundle_name
        if part_dir.exists():
            shutil.rmtree(part_dir, ignore_errors=True)

        bundle: Optional[BundleResult] = None
        error_str: Optional[str] = None
        warning_str: Optional[str] = None
        converter, dispose = _get_process_converter(do_ocr, force_ocr)
        try:
            source = DocumentStream(name=filename, stream=io.BytesIO(data))
            result = converter.convert(source, raises_on_error=False)
            if result.status in (
                    ConversionStatus.SUCCESS,
                    ConversionStatus.PARTIAL_SUCCESS,
            ):
                bundle = _materialize_bundle(
                    result, part_dir, Path(filename).stem,
                    picture_name_prefix=f"{idx:02d}-",
                )
                if result.status == ConversionStatus.PARTIAL_SUCCESS:
                    err_desc = "; ".join(e.error_message for e in result.errors)
                    warning_str = (
                        f"【docling】子文档部分页面解析失败: {filename} -- {err_desc}"
                    )
            else:
                err_desc = (
                        "; ".join(e.error_message for e in result.errors)
                        or str(result.status)
                )
                error_str = f"docling 转换失败({result.status.value}): {err_desc}"
        except Exception as exc:
            error_str = f"{type(exc).__name__}: {exc}"
            LOGGER.error(
                f"【docling】子文档解析失败(子进程): {filename} -- "
                f"{type(exc).__name__}: {exc}"
            )
        finally:
            # 复用时仅归还临时显存; 非缓存（docling_parse 后端）整体释放;
            # 批次结束进程池销毁兜底清零 CUDA 上下文
            _release_after_conversion(converter, dispose)

        records.append((idx, bundle, error_str, warning_str))

    return records


async def convert_pdfs_to_bundles(
        parts: List[Tuple[str, bytes]],
        bundle_names: List[str],
        *,
        do_ocr: bool = True,
        force_ocr: bool = True,
        batch_concurrency: int = 1,
        on_part_converted: Optional[Callable[[int, str, Optional[Exception]], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
) -> List[Union[BundleResult, Exception]]:
    """批量转换多个 PDF 子文档（进程池并行: 每子文档一个独立任务）。

    进程隔离并行模式: 每个子进程自建并持有独立 converter 实例, 进程间状态
    彻底隔离, 不依赖 GC 回收 C++ 状态（docling-parse C++ 后端与 onnxruntime
    会在 converter 实例内累积内存且不随单次转换释放, 见官方 FAQ 的
    std::bad_alloc 案例）。worker 跨任务复用摊薄 spawn 启动开销; 批次内
    子进程不回收重生（Windows + CUDA 下回收重生会挂死, 见 _run_pool 注释）,
    批次结束进程池销毁时 CUDA 上下文 / 显存碎片随进程退出统一归零。

    参数:
        parts: [(文件名, PDF 字节), ...], 顺序即返回顺序;
        bundle_names: 与 parts 等长, 各子文档产物目录名（通常 ``{job_id}_part_{idx:02d}``）;
        batch_concurrency: 最大并行子文档数（进程池 worker 数, 另受 CPU 核数
            上限约束）; 每个 worker 独立自建 converter（内存峰值 ≈ 槽位数 ×
            3~4GB）, 2~3 推荐（32GB 机器）;
        on_part_converted: 子文档完成回调 ``(idx, filename, error)``, 在父进程
            汇总线程触发; 每个 part 保证恰好回调一次（含失败、含取消跳过）,
            供调用方经 call_soon_threadsafe 向事件循环转发进度。
        should_cancel: 取消探测回调（父进程汇总线程调用, 需线程安全）; 返回
            True 时回收本次转换拥有的解析进程，剩余 part 以取消错误填充
            并照常回调；父进程每秒检查，不依赖原生转换自行返回。

    返回:
        与 parts 等长: 成功为 BundleResult, 失败为 Exception;
        单个子文档失败不中断其余子文档。
    """
    if len(bundle_names) != len(parts):
        raise ValueError("bundle_names 长度必须与 parts 一致")

    total = len(parts)
    stop_requested = threading.Event()

    def _cancelled() -> bool:
        return stop_requested.is_set() or (should_cancel is not None and should_cancel())

    def _run() -> List[Union[BundleResult, Exception]]:
        results: List[Union[BundleResult, Exception, None]] = [None] * total
        if total == 0:
            return []

        # 阶段批大小在子进程内另行设置（见 _process_chunk_in_process）
        workers = max(1, min(int(batch_concurrency), total))

        # 回调追踪: 保证"每个 part 恰好一条事件"的契约, finally 兜底补发缺失事件
        fired = [False] * total

        def _tracked_fire(idx_: int, filename_: str, error_: Optional[Exception]) -> None:
            if fired[idx_]:
                return
            fired[idx_] = True
            _fire_part_callback(on_part_converted, idx_, filename_, error_)

        def _run_in_processes() -> None:
            """进程池并行（进程隔离并行模式）: 按子文档数均衡分块, 每个子进程
            自建 converter 实例, 进程间内存彻底隔离, 不依赖 GC 回收 C++ 状态。"""
            # 取消由父进程定期探测并回收自己拥有的解析进程，不再依赖
            # Manager/Event 的 IPC，也不继承 Celery 进程内的数据库连接。
            context = multiprocessing.get_context("spawn")

            # 每子文档一个独立任务: 进度回调粒度 = 子文档级（前端进度逐片跳动）;
            # 进程池 worker 跨任务复用, spawn 开销按整批摊薄而非按任务计
            cpu_count = multiprocessing.cpu_count()
            pool_workers = max(1, min(workers, cpu_count))
            chunks = [
                [(i, parts[i][0], parts[i][1], bundle_names[i])]
                for i in range(total)
            ]
            LOGGER.info(
                f"【docling】进程池并行解析: {total} 个子文档（每子文档一个任务）, "
                f"{pool_workers} 个进程（CPU 核数: {cpu_count}）"
            )

            _run_pool(chunks, pool_workers, context)

        def _run_pool(chunks, pool_workers, context) -> None:
            from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED

            # 子进程不回收重生（max_tasks_per_child=None, 标准库不接受 ≤0）:
            # Windows + CUDA 下子进程回收重生会挂死——表现为跑到一定数量的
            # 子文档后无声停滞（无报错、GPU 归零）。批次结束进程池销毁,
            # CUDA 上下文/分配器碎片/各类原生状态随进程退出彻底归零
            with ProcessPoolExecutor(
                    max_workers=pool_workers,
                    mp_context=context,
                    max_tasks_per_child=None,
            ) as executor:
                future_to_chunk = {
                    executor.submit(
                        _process_chunk_in_process,
                        chunk,
                        do_ocr,
                        force_ocr,
                        str(PROJECT_CONFIG.RAG_OUTPUT_DIR),
                        None,
                    ): chunk
                    for chunk in chunks
                }
                def _completed():
                    pending = set(future_to_chunk)
                    while pending:
                        # 即使所有原生转换均卡住，也每秒探测取消，不依赖完成回调。
                        if _cancelled():
                            for future in pending:
                                future.cancel()
                            _terminate_owned_pool(executor)
                            for idx, (filename, _) in enumerate(parts):
                                if not fired[idx]:
                                    error = ConversionCancelledError(_CANCEL_MESSAGE)
                                    results[idx] = error
                                    _tracked_fire(idx, filename, error)
                            return
                        done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
                        yield from done

                for future in _completed():
                    chunk = future_to_chunk[future]
                    try:
                        chunk_records = future.result()
                    except Exception as exc:
                        # 整块失败（子进程崩溃 / IPC 错误等）: 该块全部子文档
                        # 填充同一错误（回调契约: 每个 part 恰好一条事件）
                        LOGGER.error(
                            f"【docling】进程块处理失败: {type(exc).__name__}: {exc}"
                        )
                        for idx, filename, _, _ in chunk:
                            results[idx] = exc
                            _tracked_fire(idx, filename, exc)
                        continue
                    for idx, bundle, err_str, warn_str in chunk_records:
                        if warn_str:
                            LOGGER.warning(warn_str)
                        filename = parts[idx][0]
                        if err_str:
                            # 取消错误重建为类型化异常, 调用方按 isinstance 识别
                            error = (
                                ConversionCancelledError(err_str)
                                if err_str == _CANCEL_MESSAGE
                                else RuntimeError(err_str)
                            )
                            results[idx] = error
                            _tracked_fire(idx, filename, error)
                        else:
                            results[idx] = bundle
                            _tracked_fire(idx, filename, None)

        try:
            _run_in_processes()
        finally:
            # 回调契约兜底: 即便发生致命异常（依赖导入失败、进程池整体崩溃等）,
            # 也为尚未收到回调的 part 各补发一条事件, 调用方进度消费循环不会死等
            for idx in range(total):
                if not fired[idx]:
                    fired[idx] = True
                    _fire_part_callback(
                        on_part_converted, idx, parts[idx][0],
                        RuntimeError("子文档转换未产生回调（内部异常兜底）"),
                    )

        return results  # type: ignore[return-value]

    conversion = asyncio.create_task(asyncio.to_thread(_run))
    try:
        return await asyncio.shield(conversion)
    except asyncio.CancelledError:
        stop_requested.set()
        # 清理解析进程完成前不释放文档锁，防止删除与落盘并发。
        await asyncio.shield(conversion)
        raise
