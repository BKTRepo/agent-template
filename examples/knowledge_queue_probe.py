"""仅本机验证 Worker 注册的解析槽占用探针，不在正式任务中导入。"""
from pathlib import Path
import time


def register(celery):
    from celery import Task
    @celery.task(name="examples.knowledge_queue.block_parse", base=Task)
    def block_parse(marker, duration):
        # 标记文件必须位于本机验证目录，禁止调用者传任意服务器路径。
        from examples.knowledge_queue_environment import ROOT
        target = Path(marker).resolve()
        if not target.is_relative_to(ROOT.resolve()):
            raise ValueError("probe marker outside demo directory")
        target.write_text("running", encoding="utf-8")
        time.sleep(min(20, max(0, duration)))
        return "done"
