# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from applications.base.services.scaffold import UpperStr
from enums import TaskCenterScheduler, TaskCenterStatus


class TaskCenterCreate(BaseModel):
    task_name: str = Field(..., max_length=255, description="任务名称")
    task_desc: Optional[str] = Field(None, max_length=2048, description="任务描述")
    task_type: Optional[str] = Field(None, max_length=128, description="任务分类")
    task_celery_node: Optional[str] = Field(None, max_length=1024, description="任务调度节点")
    task_kwargs: Optional[Dict[str, Any]] = Field(None, description="任务执行参数")
    task_celery_scheduler: Optional[TaskCenterScheduler] = Field(None, description="任务调度模式")
    task_interval_expr: Optional[int] = Field(None, description="间隔秒数")
    task_datetime_expr: Optional[str] = Field(None, max_length=64, description="一次性执行时间")
    task_crontabs_expr: Optional[str] = Field(None, max_length=255, description="Cron表达式")
    task_notify: Optional[List[str]] = Field(None, description="执行反馈配置")
    task_notifier: Optional[List[str]] = Field(None, description="通知人员")
    task_enabled: Optional[bool] = Field(False, description="是否启用调度")


class TaskCenterUpdate(BaseModel):
    task_id: Optional[int] = Field(None, description="任务ID")
    task_code: Optional[str] = Field(None, max_length=64, description="任务标识代码")
    task_name: Optional[str] = Field(None, max_length=255, description="任务名称")
    task_desc: Optional[str] = Field(None, max_length=2048, description="任务描述")
    task_type: Optional[str] = Field(None, max_length=128, description="任务分类")
    task_celery_node: Optional[str] = Field(None, max_length=1024, description="任务调度节点")
    task_kwargs: Optional[Dict[str, Any]] = Field(None, description="任务执行参数")
    task_celery_time: Optional[str] = Field(None, max_length=32, description="任务调度时间")
    task_celery_status: Optional[TaskCenterStatus] = Field(None, description="任务调度状态")
    task_celery_scheduler: Optional[TaskCenterScheduler] = Field(None, description="任务调度模式")
    task_interval_expr: Optional[int] = Field(None, description="间隔秒数")
    task_datetime_expr: Optional[str] = Field(None, max_length=64, description="一次性执行时间")
    task_crontabs_expr: Optional[str] = Field(None, max_length=255, description="Cron表达式")
    task_notify: Optional[List[str]] = Field(None, description="执行反馈配置")
    task_notifier: Optional[List[str]] = Field(None, description="通知人员")
    task_enabled: Optional[bool] = Field(None, description="是否启用调度")
    task_version: Optional[int] = Field(None, description="任务版本")


class TaskCenterSelect(TaskCenterUpdate):
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=10, ge=10, description="每页数量")
    order: List[str] = Field(default=["-created_time"], description="排序字段")
    created_user: Optional[Union[UpperStr, str]] = Field(None, max_length=16, description="创建人员")
    updated_user: Optional[Union[UpperStr, str]] = Field(None, max_length=16, description="更新人员")
    state: Optional[int] = Field(default=0, description="状态(0:启用, 1:禁用)")
