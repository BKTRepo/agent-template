# -*- coding: utf-8 -*-
from tortoise import fields

from applications.base.services.scaffold import (
    MaintainMixin,
    ReserveFields,
    ScaffoldModel,
    StateModel,
    TimestampMixin,
    unique_identify,
)
from enums import TaskCenterScheduler, TaskCenterStatus


class TaskCenterInfo(ScaffoldModel, MaintainMixin, TimestampMixin, StateModel, ReserveFields):
    """任务中心-任务信息表"""

    task_name = fields.CharField(max_length=255, index=True, description="任务名称")
    task_code = fields.CharField(max_length=64, default=unique_identify, unique=True, description="任务标识代码")
    task_desc = fields.CharField(max_length=2048, null=True, description="任务描述")
    task_type = fields.CharField(max_length=128, null=True, index=True, description="任务分类")
    task_celery_node = fields.CharField(max_length=1024, null=True, description="任务调度节点")
    task_kwargs = fields.JSONField(default=dict, null=True, description="任务执行参数")
    task_celery_time = fields.DatetimeField(default=None, null=True, description="任务调度时间")
    task_celery_status = fields.CharEnumField(TaskCenterStatus, default=None, null=True, description="任务调度状态")
    task_celery_scheduler = fields.CharEnumField(TaskCenterScheduler, default=None, null=True, description="任务调度模式")
    task_interval_expr = fields.IntField(null=True, description="间隔秒数(interval)")
    task_datetime_expr = fields.CharField(max_length=64, null=True, description="一次性执行时间(datetime)")
    task_crontabs_expr = fields.CharField(max_length=255, null=True, description="Cron表达式")
    task_notify = fields.JSONField(default=None, null=True, description="执行反馈配置")
    task_notifier = fields.JSONField(default=None, null=True, description="通知人员")
    task_enabled = fields.BooleanField(default=False, index=True, description="是否启用调度")
    task_version = fields.IntField(default=0, description="任务版本(每次启动调度+1)")
    state = fields.SmallIntField(default=0, index=True, description="状态(0:启用, 1:禁用)")

    class Meta:
        table = "keenrobot_task_center"
        table_description = "任务中心-任务信息表"
        unique_together = (("task_name", "created_user"),)
        ordering = ["-updated_time"]

    def __str__(self):
        return self.task_name


class TaskCenterRecord(ScaffoldModel, MaintainMixin, TimestampMixin, StateModel, ReserveFields):
    """任务中心-执行记录表"""

    task_id = fields.BigIntField(null=True, index=True, description="任务ID")
    task_version = fields.IntField(null=True, index=True, description="任务版本(执行时快照)")
    task_name = fields.CharField(max_length=255, null=True, index=True, description="任务名称")
    task_kwargs = fields.JSONField(default=dict, null=True, description="任务执行参数快照")
    task_summary = fields.TextField(null=True, description="执行摘要")
    task_error = fields.TextField(null=True, description="错误信息")
    celery_id = fields.CharField(max_length=255, index=True, description="Celery调度ID")
    task_celery_node = fields.CharField(max_length=512, null=True, index=True, description="任务调度节点")
    celery_trace_id = fields.CharField(max_length=255, null=True, index=True, description="调度回溯ID")
    task_celery_status = fields.CharEnumField(TaskCenterStatus, default=TaskCenterStatus.RUNNING, description="任务调度状态")
    task_celery_scheduler = fields.CharEnumField(TaskCenterScheduler, default=None, null=True, description="任务调度模式")
    celery_start_time = fields.DatetimeField(null=True, description="开始时间")
    celery_end_time = fields.DatetimeField(null=True, description="结束时间")
    celery_duration = fields.CharField(max_length=64, null=True, description="耗时")

    class Meta:
        table = "keenrobot_task_center_record"
        table_description = "任务中心-执行记录表"
        indexes = (
            ("task_id", "task_version"),
            ("task_celery_status",),
            ("celery_start_time",),
            ("task_celery_status", "celery_start_time"),
        )
        ordering = ["-celery_start_time", "-id"]

    def __str__(self):
        return f"{self.celery_id or ''}-{self.task_name or ''}"
