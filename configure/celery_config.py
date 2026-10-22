# -*- coding: utf-8 -*-
import os
from functools import lru_cache
from typing import Any, Dict

from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing_extensions import Self

from common import FileUtils
from configure.project_config import PROJECT_CONFIG


class CeleryConfig(BaseSettings):
    CELERY_BEAT_SCHEDULER: str = "redbeat.schedulers:RedBeatScheduler"
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""
    CELERY_REDBEAT_REDIS_URL: str = ""
    CELERY_CONFIG: Dict[str, Any] = {}

    CELERY_LOG_DIR: str = ""
    CELERY_WORKER_LOG_FILE: str = ""
    CELERY_BEAT_LOG_FILE: str = ""
    CELERY_TASK_LOG_FILE: str = ""

    @model_validator(mode="after")
    def assemble_celery_settings(self) -> Self:
        project = PROJECT_CONFIG
        self.CELERY_BROKER_URL = project.build_redis_url(db=1)
        self.CELERY_RESULT_BACKEND = project.build_redis_url(db=2)
        self.CELERY_REDBEAT_REDIS_URL = project.build_redis_url(db=3)

        self.CELERY_LOG_DIR = os.path.join(project.OUTPUT_LOGS_DIR, "celery")
        os.makedirs(self.CELERY_LOG_DIR, exist_ok=True)
        self.CELERY_WORKER_LOG_FILE = os.path.join(self.CELERY_LOG_DIR, "celery_worker.log")
        self.CELERY_BEAT_LOG_FILE = os.path.join(self.CELERY_LOG_DIR, "celery_beat.log")
        self.CELERY_TASK_LOG_FILE = os.path.join(self.CELERY_LOG_DIR, "celery_task.log")

        task_imports = FileUtils.get_all_files(
            abspath=os.path.join(project.CELERY_SCHEDULER_DIR, "tasks"),
            return_full_path=False,
            return_precut_path="celery_scheduler.tasks.",
            startswith="task",
            extension=".py",
            exclude_startswith="__",
            exclude_endswith="__.py",
        )

        self.CELERY_CONFIG = {
            "broker_url": self.CELERY_BROKER_URL,
            "result_backend": self.CELERY_RESULT_BACKEND,
            "timezone": "Asia/Shanghai",
            "enable_utc": True,
            "task_serializer": "json",
            "accept_content": ["json"],
            "result_serializer": "json",
            "result_accept_content": ["json"],
            "task_acks_late": True,
            "worker_prefetch_multiplier": 1,
            "task_reject_on_worker_lost": True,
            "result_expires": 3600,
            "result_persistent": True,
            "task_routes": {
                "celery_scheduler.tasks.task_knowledge.process_document_task": {"queue": "knowledge_parse"},
                "celery_scheduler.tasks.task_knowledge.delete_document_task": {"queue": "knowledge_delete"},
                "celery_scheduler.tasks.task_knowledge.sweep_document_jobs_task": {"queue": "knowledge_delete"},
            },
            "task_default_queue": "default",
            "task_default_exchange": "default",
            "task_default_exchange_type": "direct",
            "task_default_routing_key": "default",
            "worker_max_tasks_per_child": 1000,
            "worker_disable_rate_limits": False,
            "task_acks_on_failure_or_timeout": False,
            "task_time_limit": 3600,
            "task_soft_time_limit": 3300,
            "beat_scheduler": self.CELERY_BEAT_SCHEDULER,
            "redbeat_redis_url": self.CELERY_REDBEAT_REDIS_URL,
            "redbeat_lock_timeout": 600,
            "redbeat_lock_renewal_interval": 420,
            "beat_schedule": {
                "knowledge-recover-document-jobs": {
                    "task": "celery_scheduler.tasks.task_knowledge.sweep_document_jobs_task",
                    "schedule": 60.0,
                    "options": {"queue": "knowledge_delete"},
                },
                "scan-task-center-tasks": {
                    "task": (
                        "celery_scheduler.tasks.task_dispatch"
                        ".scan_and_dispatch_tasks"
                    ),
                    "schedule": 60.0,
                    "options": {"queue": "default"},
                    # 默认扫描所有类型的任务，可以通过配置传递特定 task_type
                    # "kwargs": {"task_type": "example"},  # 只扫描 example 类型
                },
            },
            "worker_log_format": (
                "[%(asctime)s][%(levelname)s] -> [%(name)s][%(filename)s]"
                "[line:%(lineno)d] -> %(message)s"
            ),
            "worker_task_log_format": (
                "[%(asctime)s][%(levelname)s] -> [%(name)s][%(filename)s]"
                "[line:%(lineno)d] -> %(message)s"
            ),
            "worker_log_color": False,
            "imports": task_imports,
            "task_send_sent_event": True,
            "task_track_started": True,
            "task_ignore_result": False,
            "task_store_eager_result": False,
            "worker_send_task_events": True,
            "broker_connection_retry_on_startup": True,
        }
        return self


@lru_cache(maxsize=1)
def get_celery_config() -> CeleryConfig:
    return CeleryConfig()


CELERY_CONFIG = get_celery_config()
