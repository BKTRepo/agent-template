# -*- coding: utf-8 -*-
from enums.base_enum_cls import StringEnum


class TaskCenterScheduler(StringEnum):
    CRON = "cron"
    INTERVAL = "interval"
    DATETIME = "datetime"


class TaskCenterStatus(StringEnum):
    PENDING = "等待执行"
    RUNNING = "正在执行"
    SUCCESS = "成功"
    FAILURE = "失败"
