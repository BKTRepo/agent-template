# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from enums import TaskCenterScheduler, TaskCenterStatus


class TaskCenterRecordCreate(BaseModel):
    task_id: Optional[int] = Field(None, description="任务ID")
    task_version: Optional[int] = Field(None, description="任务版本(执行时快照)")
    task_name: Optional[str] = Field(None, max_length=255, description="任务名称")
    task_kwargs: Optional[Dict[str, Any]] = Field(None, description="任务执行参数快照")
    task_summary: Optional[str] = Field(None, description="执行摘要")
    task_error: Optional[str] = Field(None, description="错误信息")
    celery_id: str = Field(..., max_length=255, description="Celery调度ID")
    task_celery_node: Optional[str] = Field(None, max_length=512, description="任务调度节点")
    celery_trace_id: Optional[str] = Field(None, max_length=255, description="调度回溯ID")
    task_celery_status: Optional[TaskCenterStatus] = Field(TaskCenterStatus.RUNNING, description="任务调度状态")
    task_celery_scheduler: Optional[TaskCenterScheduler] = Field(None, description="任务调度模式")
    celery_start_time: Optional[str] = Field(None, max_length=32, description="开始时间")
    celery_end_time: Optional[str] = Field(None, max_length=32, description="结束时间")
    celery_duration: Optional[str] = Field(None, max_length=64, description="耗时")


class TaskCenterRecordUpdate(BaseModel):
    task_celery_status: Optional[TaskCenterStatus] = Field(None, description="任务调度状态")
    celery_end_time: Optional[str] = Field(None, max_length=32, description="结束时间")
    task_summary: Optional[str] = Field(None, description="执行摘要")
    task_error: Optional[str] = Field(None, description="错误信息")
    celery_duration: Optional[str] = Field(None, max_length=64, description="耗时")


class TaskCenterRecordSelect(BaseModel):
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=10, ge=10, description="每页数量")
    order: List[str] = Field(default=["-celery_start_time", "-id"], description="排序字段")

    celery_id: Optional[str] = Field(None, max_length=255, description="调度ID")
    task_id: Optional[int] = Field(None, description="任务ID")
    task_version: Optional[int] = Field(None, description="任务版本")
    task_name: Optional[str] = Field(None, max_length=255, description="任务名称")
    task_celery_node: Optional[str] = Field(None, max_length=512, description="任务调度节点")
    task_celery_status: Optional[str] = Field(None, max_length=32, description="任务调度状态")
    task_celery_scheduler: Optional[str] = Field(None, max_length=32, description="任务调度模式")
    celery_start_time_begin: Optional[str] = Field(None, max_length=32, description="开始时间起")
    celery_start_time_end: Optional[str] = Field(None, max_length=32, description="开始时间止")
    celery_end_time_begin: Optional[str] = Field(None, max_length=32, description="结束时间起")
    celery_end_time_end: Optional[str] = Field(None, max_length=32, description="结束时间止")
