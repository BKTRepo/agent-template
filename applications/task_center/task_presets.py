# -*- coding: utf-8 -*-
from celery_scheduler.tasks.task_example import task_example

TASK_CENTER_PRESETS = [
    {
        "preset_key": "example",
        "task_type": "example",
        "task_name": "示例写入任务",
        "task_desc": "向 task_example.txt 追加写入，含随机终止/失败事件，用于测试 Celery 执行链路",
        "task_celery_node": task_example.name,
        "task_kwargs": {
            "write_number": 100,
            "write_message": "测试文本：通过Celery异步执行函数...",
        },
        "kwargs_schema": [
            {"key": "write_number", "label": "写入行数", "required": True, "min": 1, "max": 100},
            {"key": "write_message", "label": "写入内容", "required": False},
        ],
    },
]

SCHEDULER_OPTIONS = [
    {"value": "interval", "label": "固定间隔"},
    {"value": "cron", "label": "Cron 表达式"},
    {"value": "datetime", "label": "一次性定时"},
]
