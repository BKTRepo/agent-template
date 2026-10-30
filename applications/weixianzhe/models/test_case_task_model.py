# -*- coding: utf-8 -*-
"""
@Author  : weixianzhe
@Project : KeenRobot
@Module  : test_case_task_model.py
@DateTime: 2026/6/11
"""
from tortoise import fields

from applications.base.services.scaffold import (
    ScaffoldModel,
    TimestampMixin,
    MaintainMixin,
)


class TestCaseTask(ScaffoldModel, TimestampMixin, MaintainMixin):
    """测试用例生成任务模型"""

    folder_path = fields.CharField(max_length=500, default="", description="输出文件夹路径")
    app_system = fields.CharField(max_length=50, default="", description="应用系统")
    requirement_name = fields.CharField(max_length=200, default="", description="需求名称")
    status = fields.CharField(max_length=20, default="generating", description="任务状态")
    error_reason = fields.CharField(max_length=500, null=True, default="", description="错误原因")

    class Meta:
        table = "keenrobot_test_case_task"
