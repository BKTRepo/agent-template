"""非 Docling 文档也放进本次任务独占的子进程，取消只回收自身进程树。"""
import asyncio
import multiprocessing

from .job_control import DocumentCancelled


def _load(path, file_type, connection):
    try:
        from applications.wrq.knowledge_base.services.document_loader import load_document_pages
        markdown = "\n\n".join(p.page_content for p in load_document_pages(path, file_type))
        connection.send((True, markdown))
    except Exception as exc:
        connection.send((False, f"{type(exc).__name__}: {exc}"))
    finally:
        connection.close()


def terminate_owned(process):
    import psutil
    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    for child in reversed(descendants):
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    if process.is_alive():
        process.terminate()
    process.join(timeout=2)
    if process.is_alive():
        process.kill()
    process.join(timeout=2)
    _, alive = psutil.wait_procs(descendants, timeout=2)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=2)


def _run(path, file_type, stop, worker):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(path, file_type, sender))
    process.start()
    sender.close()
    try:
        while True:
            if stop.is_set():
                raise DocumentCancelled("解析已取消")
            if receiver.poll(.1):
                ok, result = receiver.recv()
                if not ok:
                    raise ValueError(result)
                return result
            if not process.is_alive():
                raise RuntimeError("文档解析子进程异常退出")
    finally:
        receiver.close()
        if process.is_alive():
            terminate_owned(process)
        else:
            process.join(timeout=2)
        process.close()


async def parse_in_process(path, file_type, stop, *, worker=_load):
    task = asyncio.create_task(asyncio.to_thread(_run, path, file_type, stop, worker))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        stop.set()
        # 线程内负责回收子进程；回收完成后才允许释放同文档租约。
        await asyncio.gather(task, return_exceptions=True)
        raise
