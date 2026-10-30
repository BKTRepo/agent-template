# -*- coding: utf-8 -*-
from applications.task_center.services.task_crud import TaskCenterCrud
from applications.task_center.services.task_record_crud import TaskCenterRecordCrud


async def get_task_crud() -> TaskCenterCrud:
    return TaskCenterCrud()


async def get_task_record_crud() -> TaskCenterRecordCrud:
    return TaskCenterRecordCrud()
